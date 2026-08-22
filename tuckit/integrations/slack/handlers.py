"""The app_mention job: identity, placeholder, interpretation, result card.

Identity is resolved BEFORE the placeholder is posted -- see resolve_member()
below. An unlinked mention gets an ephemeral connect prompt and nothing else;
a public "working on it..." that resolves to nothing is worse than a quiet
ephemeral answer, and the view that enqueued this job does not yet know who
the person is, so this ordering can only happen here, in the slow path.
"""
import logging

from django.conf import settings

from tuckit.core.models import Area, Slice
from tuckit.core.services.refs import slice_ref
from tuckit.integrations.slack import cards
from tuckit.integrations.slack.api import SlackApiError, SlackClient
from tuckit.integrations.slack.apply import apply_intents
from tuckit.integrations.slack.identity import connect_blocks, connect_state, resolve_member
from tuckit.integrations.slack.interpret import (
    InterpretationUnavailable, TooManyIntents, interpret,
)
from tuckit.integrations.slack.models import SlackInstall
from tuckit.integrations.slack.queue import job

logger = logging.getLogger(__name__)

MAX_THREAD_MESSAGES = 100


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
        url = f"{settings.TUCKIT_BASE_URL}/slack/connect?state={connect_state(install, slack_user_id)}"
        client.post_ephemeral(
            channel=channel, user=slack_user_id, thread_ts=reply_ts,
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

    results = apply_intents(org=org, member=member, intents=intents)
    reply(
        text="Filed",
        blocks=cards.result_blocks(
            results=results,
            actor_name=member.user.get_full_name() or member.user.email,
            message_count=len(texts),
            board_url=f"{settings.TUCKIT_BASE_URL}/{org.slug}/",
        ),
    )
