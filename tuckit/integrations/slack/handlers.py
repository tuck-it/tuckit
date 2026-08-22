"""The app_mention job: identity, placeholder, interpretation, result card.

Identity is resolved BEFORE the placeholder is posted -- see resolve_member()
below. An unlinked mention gets an ephemeral connect prompt and nothing else;
a public "working on it..." that resolves to nothing is worse than a quiet
ephemeral answer, and the view that enqueued this job does not yet know who
the person is, so this ordering can only happen here, in the slow path.
"""
import logging
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.utils import timezone

from tuckit.core.models import Area, Slice
from tuckit.core.services.refs import slice_ref
from tuckit.integrations.slack import cards
from tuckit.integrations.slack.api import SlackApiError, SlackClient
from tuckit.integrations.slack.apply import apply_intents
from tuckit.integrations.slack.identity import connect_blocks, connect_state, resolve_member
from tuckit.integrations.slack.interpret import (
    InterpretationUnavailable, TooManyIntents, interpret,
)
from tuckit.integrations.slack.models import SlackInstall, SlackUnfurl
from tuckit.integrations.slack.queue import job

logger = logging.getLogger(__name__)

MAX_THREAD_MESSAGES = 100
UNFURL_COOLDOWN = timedelta(minutes=60)


def _open_slices(org) -> list[tuple[str, str]]:
    rows = Slice.objects.filter(org=org, status="open").select_related("org")[:300]
    return [(slice_ref(row), row.title) for row in rows]


def _thread_texts(client, *, channel: str, event: dict) -> list[str]:
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        # Mentioned at channel top level: that one message is the whole input.
        return [event.get("text", "")]
    messages = client.conversations_replies(
        channel=channel, thread_ts=thread_ts, limit=MAX_THREAD_MESSAGES,
    )
    return [m.get("text", "") for m in messages]


@job("slack.app_mention")
def handle_app_mention(*, team_id: str, event: dict) -> None:
    install = (
        SlackInstall.objects.filter(team_id=team_id).select_related("org").first()
    )
    if install is None:
        logger.warning("app_mention for unknown team %s", team_id)
        return

    client = SlackClient(install.bot_token)
    channel = event.get("channel", "")
    slack_user_id = event.get("user", "")
    reply_ts = event.get("thread_ts") or event.get("ts")

    member = resolve_member(install, slack_user_id)
    if member is None:
        # No placeholder: nothing is going to happen, and a public "working on
        # it…" that resolves to nothing is worse than an ephemeral answer.
        #
        # thread_ts is the mention's OWN thread, never reply_ts. reply_ts falls
        # back to the mention's ts, and an ephemeral addressed to a message
        # that has no thread yet is accepted (ok:true) and then shown only
        # inside a thread nobody has opened -- the channel shows nothing at
        # all, because an ephemeral leaves no reply count behind the way the
        # placeholder does. This button IS the discovery path for connecting,
        # so hiding it reads to a first-time user as "the bot is broken",
        # which is the exact failure this branch exists to avoid.
        url = f"{settings.TUCKIT_BASE_URL}/slack/connect?state={connect_state(install, slack_user_id)}"
        client.post_ephemeral(
            channel=channel, user=slack_user_id, thread_ts=event.get("thread_ts"),
            text="Connect your tuckit account to use this.",
            blocks=connect_blocks(url),
        )
        return

    texts = _thread_texts(client, channel=channel, event=event)

    # Best-effort: losing the placeholder is a worse experience, but it is not
    # a reason to abandon the work.
    placeholder_ts = None
    try:
        placeholder_ts = client.post_message(
            channel=channel, thread_ts=reply_ts,
            text=cards.placeholder_text(len(texts)),
        )
    except SlackApiError:
        logger.warning("could not post the placeholder; continuing", exc_info=True)

    def reply(*, text: str, blocks: list) -> None:
        if placeholder_ts:
            client.update_message(channel=channel, ts=placeholder_ts, text=text, blocks=blocks)
        else:
            client.post_message(channel=channel, thread_ts=reply_ts, text=text, blocks=blocks)

    org = install.org
    try:
        intents = interpret(
            messages=texts,
            area_slugs=list(Area.objects.filter(org=org).values_list("slug", flat=True)),
            open_slices=_open_slices(org),
        )
    except TooManyIntents:
        reply(text="Too many things", blocks=cards.failure_blocks(
            "This thread looks like more than five separate things, so I have not "
            "filed anything. Tell me which one to start with.",
        ))
        return
    except InterpretationUnavailable:
        reply(text="Not configured", blocks=cards.failure_blocks(
            "This deployment has no interpretation configured, so I cannot read "
            "threads. Everything else still works.",
        ))
        return
    except Exception:
        logger.exception("interpretation failed")
        reply(text="Could not read the thread", blocks=cards.failure_blocks(
            "I could not read this thread just now. Mention me again to retry.",
        ))
        return

    # Cloud Tasks retries a failing job by calling this handler again from
    # the top, bypassing the SlackEvent dedupe that guards Slack's own
    # retries (that row is written by the view, before this job ever runs).
    # channel + the mention's own ts is stable across such a retry and needs
    # nothing new threaded through the job payload -- see apply_intents'
    # docstring for why only create_slice is covered.
    results = apply_intents(
        org=org, member=member, intents=intents,
        dedupe_key=f"slack:{channel}:{event.get('ts', '')}",
    )
    reply(
        text="Filed",
        blocks=cards.result_blocks(
            results=results,
            actor_name=member.user.get_full_name() or member.user.email,
            message_count=len(texts),
        ),
    )


def _slice_from_url(org, url: str):
    """The slice a tuckit URL points at, or None.

    Filtered by `org` -- the org that owns the Slack install doing the
    lookup, never the org slug embedded in the URL itself, since that slug is
    just text a link-paster could put anything in. Returning None rather than
    raising matters here: an error would itself confirm the slice exists,
    which is the leak this bite exists to prevent.
    """
    parsed = urlparse(url)
    slice_id = (parse_qs(parsed.query).get("slice") or [""])[0]
    if not slice_id.isdigit():
        return None
    return Slice.objects.filter(org=org, id=int(slice_id)).select_related("area", "org").first()


@job("slack.link_shared")
def handle_link_shared(*, team_id: str, event: dict) -> None:
    """Unfurl tuckit links pasted into Slack, permission-checked and rate-limited.

    Two rules, both borrowed from Linear, both about not leaking:

    1. The person who pasted the link must resolve to a member of the org
       that owns the ref, via resolve_member(). An unresolvable person, or a
       ref belonging to another org, produces no unfurl at all -- not an
       error message, which would itself confirm the ref exists. This is the
       one place in this slice where silence, not a spoken failure, is
       correct.
    2. The same ref is not re-expanded within UNFURL_COOLDOWN, so a ref
       repeated in an active channel does not redraw a card every time.
    """
    install = SlackInstall.objects.filter(team_id=team_id).select_related("org").first()
    if install is None:
        return

    member = resolve_member(install, event.get("user", ""))
    if member is None:
        return

    # An event with no message_ts has no message to attach an unfurl to.
    # chat.unfurl(ts="") is ACCEPTED by Slack -- ok:true -- and draws nothing,
    # and the cooldown row written below would then suppress any later attempt
    # at the same ref for an hour. So the guard is about never burning the
    # cooldown on a call that cannot land.
    #
    # It is a guard, NOT a fix for an observed failure. It shipped in v0.65.0
    # on the theory that Slack was sending a second, composer-sourced event
    # without a ts; the log line below has never fired since, so that theory
    # has no evidence behind it. Do not cite it as the reason unfurls once
    # looked broken -- that was a synthetic URL nobody would ever share.
    # The log names no ref, title or URL: this handler's silence rule covers
    # logs too.
    message_ts = event.get("message_ts") or ""
    if not message_ts:
        logger.info(
            "skipping a link_shared with no message_ts (source=%s, links=%d)",
            event.get("source", "?"), len(event.get("links", [])),
        )
        return

    channel = event.get("channel", "")
    unfurls = {}
    expanded_refs = []
    cutoff = timezone.now() - UNFURL_COOLDOWN
    for link in event.get("links", []):
        url = link.get("url", "")
        found = _slice_from_url(install.org, url)
        if found is None:
            continue
        ref = slice_ref(found)
        recent = SlackUnfurl.objects.filter(
            install=install, channel=channel, ref=ref, last_unfurled_at__gte=cutoff,
        ).exists()
        if recent:
            continue
        unfurls[url] = cards.unfurl_block(found)
        expanded_refs.append(ref)

    if not unfurls:
        return
    try:
        SlackClient(install.bot_token).chat_unfurl(
            channel=channel, ts=message_ts, unfurls=unfurls,
        )
    except SlackApiError:
        # Deliberately swallowed, not just uncaught: this is the one path in
        # the whole integration where a failure must not speak. Any message
        # back -- to Slack, to a user-visible log, to anywhere -- would tell
        # someone whether a ref they are not permitted to see exists, which
        # is exactly the leak this bite exists to prevent. The log line below
        # carries no ref, title or URL for the same reason.
        logger.warning("chat.unfurl failed for team %s", team_id)
        return

    # Written only now, after Slack accepted the call. The cooldown record is
    # a note that a card was drawn, so a failed unfurl must not leave one
    # behind: it would suppress that ref for the next hour and the reader
    # would get silence for a card they never saw.
    for ref in expanded_refs:
        SlackUnfurl.objects.update_or_create(install=install, channel=channel, ref=ref)
