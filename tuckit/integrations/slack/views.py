import json
import logging
import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tuckit.core.services.orgs import is_org_admin
from tuckit.integrations.slack.api import SlackApiError, exchange_oauth_code
from tuckit.integrations.slack.identity import (
    CONNECT_STATE_MAX_AGE_SECONDS, CONNECT_STATE_SALT, connect_blocks, connect_state,
)
from tuckit.integrations.slack.models import SlackEvent, SlackIdentity, SlackInstall
from tuckit.integrations.slack.queue import enqueue
from tuckit.integrations.slack.signing import SlackSignatureError, verify_signature
from tuckit.web.htmx import redirect_response
from tuckit.web.views.settings_shell import settings_context

logger = logging.getLogger(__name__)

# Slack event type -> job name. An event we do not handle is acknowledged and
# dropped: Slack must never be left retrying something we will never process.
EVENT_JOBS = {
    "app_mention": "slack.app_mention",
    "link_shared": "slack.link_shared",
}


class _DuplicateDelivery(Exception):
    """Slack re-delivered an event_id we have already accepted.

    Its own type so the `except` in slack_events can mean exactly the
    SlackEvent row conflict and nothing else. Catching `IntegrityError`
    around the whole atomic block would also swallow one raised by
    _enqueue_or_release, which runs from the on_commit hook and so surfaces
    at the block's __exit__, inside the same try. That is a lost event
    wearing a duplicate's clothes; see the comment at the raise site.
    """


def _enqueue_or_release(event_id: str, job_name: str, payload: dict) -> None:
    """Queue the job, and hand the idempotency token back if that fails.

    The SlackEvent row exists to make Slack's retry safe, so it must not
    outlive a delivery that queued nothing. If `enqueue` raises (Cloud Tasks
    unreachable, IAM refused, queue misconfigured) and the row stayed, Slack's
    retry of the same event_id would hit the row, take the duplicate-delivery
    branch below, answer 200 and queue nothing -- the event would be lost with
    no job, no placeholder and no reply. Deleting it first means the retry is
    allowed to do the work.

    This runs from transaction.on_commit, so the row is already committed and
    the delete is its own statement rather than a rollback of an open block.
    The re-raise is deliberate: it becomes a 500, which is the only thing that
    makes Slack retry at all.

    THE TRADE THIS MAKES, and what is still exposed
    -----------------------------------------------
    Releasing the token trades "the event is lost forever" for "the event may
    be executed twice". Both outcomes are reachable, because we cannot tell a
    backend that never accepted the task from one that accepted it and then
    failed to say so: if `enqueue` raises AFTER the queue has taken the task
    (a client-side timeout on an accepted submit, a dropped response), we
    delete the row anyway, Slack retries, and the job runs a SECOND time.

    That is the right way round. Losing the event is silent and permanent:
    no job, no placeholder, no reply, and no further retry coming, so nobody
    finds out until someone asks why the bot ignored them. A double execution
    is visible and bounded, and the operation this integration exists to
    perform is idempotent under it: create_slice dedupes on `external_key`,
    so a second run finds the slice the first one made instead of making
    another.

    EXACTLY TWO of the writes a re-run makes to the board are not covered by
    that: `add_note` and `create_area`. Neither has an idempotency key (see
    the NOTE comments on apply._add_note and apply._create_area), so running
    the same job twice appends the note a second time or creates a second
    area with the same name. The fourth intent, `ask_clarification`, writes
    nothing and is safe. Slack-side, a re-run also posts a second placeholder
    and a second result card in the thread, which is noise rather than
    corrupted data.

    Give those two a key (or make the queue submit itself idempotent) before
    treating a double execution here as harmless, and re-read this paragraph
    if an intent type is added: a new non-idempotent operation joins the
    exposed list silently, because nothing in the type system says so.
    """
    try:
        enqueue(job_name, payload)
    except Exception:
        SlackEvent.objects.filter(event_id=event_id).delete()
        raise


@csrf_exempt
@login_not_required
@require_POST
def slack_events(request):
    """The single entry point Slack calls for every event subscription.

    No org slug in the path, so TenantMiddleware never runs on this route;
    the org is resolved from `team_id` inside the enqueued payload, by the
    job handler, not here.
    """
    # request.body FIRST. Anything that parses the request (request.POST,
    # request.GET, a form parser) re-serialises it and the HMAC stops
    # matching what Slack actually signed.
    raw_body = request.body
    try:
        verify_signature(
            signing_secret=settings.SLACK_SIGNING_SECRET,
            timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
            raw_body=raw_body,
            signature=request.headers.get("X-Slack-Signature", ""),
        )
    except SlackSignatureError as exc:
        logger.warning("rejected a Slack request: %s", exc)
        return HttpResponse(status=401)

    payload = json.loads(raw_body or b"{}")

    if payload.get("type") == "url_verification":
        return JsonResponse({"challenge": payload.get("challenge", "")})

    event = payload.get("event") or {}
    job_name = EVENT_JOBS.get(event.get("type", ""))
    event_id = payload.get("event_id", "")
    if not job_name or not event_id:
        return HttpResponse(status=200)

    try:
        with transaction.atomic():
            try:
                SlackEvent.objects.create(event_id=event_id)
            except IntegrityError as exc:
                # Scoped to THIS statement on purpose. Only the unique
                # constraint on event_id proves another delivery already owns
                # this event; every other IntegrityError means something else
                # entirely. In particular _enqueue_or_release runs from the
                # on_commit hook below, so anything it raises surfaces at this
                # atomic block's __exit__ -- inside the outer try. Catching
                # IntegrityError out there would answer 200 to a failed
                # enqueue, Slack would never retry, and the event would be
                # lost silently: the exact failure _enqueue_or_release exists
                # to close. Re-raised as a distinct type so the two cannot be
                # confused; pinned by
                # tests/integrations/slack/test_events_endpoint.py::test_an_integrity_error_from_the_enqueue_path_is_not_read_as_a_duplicate.
                raise _DuplicateDelivery(event_id) from exc
            # transaction.on_commit, not a bare call: the SlackEvent row must
            # be durable before the job exists, or a retry that arrives while
            # this transaction is still open would not see the row yet, miss
            # the IntegrityError below, and queue the job a second time. This
            # ordering is pinned by
            # tests/integrations/slack/test_events_endpoint.py::test_the_job_is_queued_only_after_the_row_commits,
            # which wraps the request in an outer atomic block so on_commit
            # hooks defer to the outermost commit -- a bare enqueue() fails
            # that test. What remains untestable in a single process is the
            # genuine concurrent race (two requests interleaved); the DB
            # unique constraint on event_id is the defence there, not a test.
            transaction.on_commit(
                lambda: _enqueue_or_release(
                    event_id, job_name,
                    {"team_id": payload.get("team_id", ""), "event": event},
                )
            )
    except _DuplicateDelivery:
        # A row for this event_id already exists, which means an earlier
        # delivery got as far as queueing the job -- a failed enqueue takes
        # the row back out again (see _enqueue_or_release), so the row's
        # presence really does mean the work is already on its way. Nothing
        # to do but ack, so Slack stops retrying.
        return HttpResponse(status=200)

    return HttpResponse(status=200)


# --- Install OAuth flow ---
#
# Everything the bot needs and nothing else. users:read, users:read.email,
# message.channels, message.im and reactions:write are deliberately absent --
# see the slice constraints before adding to this list. users:read went out
# with SlackClient.users_info: every name the bot prints comes from the
# OrgMember behind the Slack user (member.user), never from a Slack profile
# lookup. A granted scope cannot be narrowed without re-prompting every
# installed workspace, so an unused one is not free.
BOT_SCOPES = [
    "app_mentions:read", "chat:write", "channels:history", "groups:history",
    "links:read", "links:write", "commands",
]
INSTALL_STATE_SALT = "slack-install"
STATE_MAX_AGE_SECONDS = 600

# Session key for a re-point awaiting confirmation. Connecting a Slack
# workspace is an org-level configuration change with real consequences (the
# bot token changes, so does where every card and unfurl goes), so a second
# team_id arriving for an org that already has an install is never applied
# silently -- see slack_install_callback and slack_install_confirm below.
PENDING_SWITCH_SESSION_KEY = "slack_pending_switch"


def _callback_url(request) -> str:
    return request.build_absolute_uri(reverse("web:slack_install_callback"))


def slack_install_begin(request):
    """Start the OAuth handshake. Runs inside TenantMiddleware (org-scoped
    URL), so request.org is already resolved and request.user is already
    confirmed to be an active member of it. Connecting (or re-pointing) the
    org's Slack workspace is an org-level configuration change, the same
    class of action as slack_disconnect, so it is admin-gated the same way
    -- membership alone is not enough."""
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
    state = signing.dumps({"org_id": org.id}, salt=INSTALL_STATE_SALT)
    query = urlencode({
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": ",".join(BOT_SCOPES),
        "redirect_uri": _callback_url(request),
        "state": state,
    })
    return redirect(f"https://slack.com/oauth/v2/authorize?{query}")


def slack_install_callback(request):
    """No org slug in the path -- Slack will not carry one through the round
    trip -- so the org travels in the signed `state` parameter instead. An
    unsigned or unverified state would let anyone bind their own Slack
    workspace to somebody else's org, which is the whole security property
    of this endpoint.
    """
    try:
        state = signing.loads(
            request.GET.get("state", ""), salt=INSTALL_STATE_SALT, max_age=STATE_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return HttpResponse("invalid state", status=400)

    from tuckit.core.models import Org, OrgMember

    org = Org.objects.filter(id=state.get("org_id")).first()
    # OrgMember.objects is the ACTIVE manager (ended_at__isnull=True). A
    # member who has since left the org, or someone who was never a member
    # of the org the state names, must not be able to complete the install.
    membership = OrgMember.objects.filter(org=org, user=request.user).first() if org else None
    if membership is None:
        return HttpResponse("invalid state", status=400)

    # Same rule as slack_install_begin: reaching this endpoint with a
    # validly-signed state proves membership, not permission. A non-admin who
    # somehow replays or is handed a state naming their own org must still be
    # refused here, not just kept off the Connect button.
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")

    try:
        data = exchange_oauth_code(code=request.GET.get("code", ""), redirect_uri=_callback_url(request))
    except SlackApiError as exc:
        messages.error(request, f"Slack refused the install: {exc}")
        return redirect("web:settings_slack", org_slug=org.slug)

    new_team_id = data["team"]["id"]
    existing = SlackInstall.objects.filter(org=org).first()
    if existing is not None and existing.team_id != new_team_id:
        # One team_id maps to exactly one org, and re-pointing an existing
        # install asks first: stash the exchanged credentials and send the
        # admin to the settings page rather than overwriting a working
        # integration underneath whoever is currently relying on it.
        request.session[PENDING_SWITCH_SESSION_KEY] = {
            "org_id": org.id,
            "team_id": new_team_id,
            "team_name": data["team"].get("name", ""),
            "bot_token": data["access_token"],
            "bot_user_id": data.get("bot_user_id", ""),
            # Stamped so slack_install_confirm can refuse a re-point that
            # sat unconfirmed past STATE_MAX_AGE_SECONDS -- Django's default
            # session lifetime is ~2 weeks, far longer than a bot token
            # authorization should remain actionable by whoever (possibly
            # someone else entirely, by then) happens to click Confirm.
            "created_at": time.time(),
        }
        messages.info(
            request,
            f"This org is already connected to '{existing.team_name or existing.team_id}'. "
            f"Confirm on the Slack settings page to switch to "
            f"'{data['team'].get('name', new_team_id)}' instead.",
        )
        return redirect("web:settings_slack", org_slug=org.slug)

    SlackInstall.objects.update_or_create(
        org=org,
        defaults={
            "team_id": new_team_id,
            "team_name": data["team"].get("name", ""),
            "bot_token": data["access_token"],
            "bot_user_id": data.get("bot_user_id", ""),
            "installed_by": membership,
        },
    )
    messages.success(request, f"Connected to {data['team'].get('name', 'Slack')}.")
    return redirect("web:settings_slack", org_slug=org.slug)


# --- Settings page ---


def _pop_pending_switch_if_expired(request, org):
    """Return the org's pending re-point if it exists and is still within
    STATE_MAX_AGE_SECONDS of when it was stashed. Reuses that constant
    rather than a second number: the signed `state` that authorized the
    OAuth exchange in the first place is only valid for that same window, so
    a re-point proposal outliving it is stale by the same standard. An
    expired (or otherwise absent-for-this-org) entry is garbage-collected
    here rather than left to rot in the session."""
    pending = request.session.get(PENDING_SWITCH_SESSION_KEY)
    if not pending or pending.get("org_id") != org.id:
        return None
    if time.time() - pending.get("created_at", 0) > STATE_MAX_AGE_SECONDS:
        del request.session[PENDING_SWITCH_SESSION_KEY]
        return None
    return pending


def settings_slack(request):
    org = request.org
    if request.GET.get("cancel_slack_switch"):
        pending = request.session.get(PENDING_SWITCH_SESSION_KEY)
        if pending and pending.get("org_id") == org.id:
            del request.session[PENDING_SWITCH_SESSION_KEY]
    ctx = settings_context(request, active="org_slack")
    ctx["org"] = org
    ctx["install"] = SlackInstall.objects.filter(org=org).select_related("installed_by__user").first()
    ctx["pending_switch"] = _pop_pending_switch_if_expired(request, org)
    return render(request, "web/settings/slack.html", ctx)


@require_POST
def slack_install_confirm(request):
    """Apply a re-point that slack_install_callback held back for
    confirmation. Admin-gated for the same reason slack_install_begin is --
    and re-checked here rather than trusted from the moment the pending
    switch was stashed, because the person confirming may not be the same
    person (or even the same admin) who started the OAuth hop."""
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
    pending = _pop_pending_switch_if_expired(request, org)
    if pending is None:
        # Either nothing was ever pending, or it just aged out and was
        # garbage-collected above. Either way there is nothing safe to
        # apply -- tell the person to start the connection over rather than
        # silently doing nothing or applying a stale token.
        messages.error(request, "That Slack connection request is no longer valid. Connect again to retry.")
        return redirect_response(request, "web:settings_slack", org_slug=org.slug)

    from tuckit.core.models import OrgMember

    membership = OrgMember.objects.filter(org=org, user=request.user).first()
    SlackInstall.objects.update_or_create(
        org=org,
        defaults={
            "team_id": pending["team_id"],
            "team_name": pending["team_name"],
            "bot_token": pending["bot_token"],
            "bot_user_id": pending["bot_user_id"],
            "installed_by": membership,
        },
    )
    del request.session[PENDING_SWITCH_SESSION_KEY]
    messages.success(request, f"Connected to {pending['team_name'] or pending['team_id']}.")
    return redirect_response(request, "web:settings_slack", org_slug=org.slug)


@require_POST
def slack_disconnect(request):
    """Revoking a workspace connection is the same class of action as
    disconnecting an OAuth app (tuckit.web.views.settings.oauth_disconnect):
    admin-only, immediate, no confirmation beyond the button itself."""
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
    SlackInstall.objects.filter(org=org).delete()
    messages.success(request, "Disconnected from Slack.")
    return redirect_response(request, "web:settings_slack", org_slug=org.slug)


# --- Connect: linking a Slack user to the tuckit member behind them ---
#
# No org slug in any of these three routes -- same reason as slack_events and
# slack_install_callback: Slack (or a Slack user's browser, arriving from an
# ephemeral message) does not carry one. The org travels inside the signed
# `state` (by way of the SlackInstall it names), never as a path parameter.


@login_not_required
def slack_connect_begin(request):
    """The unauthenticated entry the ephemeral connect button points at.

    An anonymous visitor must not lose the signed state on the way through
    login, so it is forwarded as `?next=` on the login URL rather than
    dropped. An already-authenticated visitor (clicking the button in a
    browser where they are already signed into tuckit) skips the login hop
    entirely and goes straight to the callback.
    """
    state = request.GET.get("state", "")
    callback_url = f"{reverse('web:slack_connect_callback')}?{urlencode({'state': state})}"
    if request.user.is_authenticated:
        return redirect(callback_url)
    return redirect(f"{reverse('web:login')}?{urlencode({'next': callback_url})}")


@login_required
def slack_connect_callback(request):
    """Complete the link: the person currently logged into tuckit becomes the
    OrgMember behind this Slack user, for this install.

    Reached only by a person clicking a button while logged into tuckit --
    never by an email match, never by a service account -- which is the whole
    point: Slack's email field is workspace-owned and unverified, so it must
    never be trusted as identity evidence.
    """
    try:
        state = signing.loads(
            request.GET.get("state", ""), salt=CONNECT_STATE_SALT,
            max_age=CONNECT_STATE_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return HttpResponse("invalid state", status=400)

    from tuckit.core.models import OrgMember

    install = SlackInstall.objects.filter(id=state.get("install_id")).select_related("org").first()
    if install is None:
        return HttpResponse("invalid state", status=400)

    # OrgMember.objects is the active manager, so an ended membership does not
    # match here either -- someone who left cannot re-link themselves.
    membership = OrgMember.objects.filter(org=install.org, user=request.user).first()
    if membership is None:
        return HttpResponse("you are not a member of this workspace", status=403)

    SlackIdentity.objects.update_or_create(
        install=install, slack_user_id=state.get("slack_user_id"),
        defaults={"member": membership},
    )
    return render(request, "web/slack/connected.html", {"org": install.org})


@csrf_exempt
@login_not_required
@require_POST
def slack_command(request):
    """POST /slack/command -- Slack slash commands.

    Verified exactly as slack_events verifies event callbacks. Slack sends
    slash commands form-encoded, so request.body must be read before
    request.POST touches the stream -- reversing the order re-serialises the
    body and the HMAC stops matching what Slack actually signed.
    """
    raw_body = request.body
    try:
        verify_signature(
            signing_secret=settings.SLACK_SIGNING_SECRET,
            timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
            raw_body=raw_body,
            signature=request.headers.get("X-Slack-Signature", ""),
        )
    except SlackSignatureError as exc:
        logger.warning("rejected a Slack slash command: %s", exc)
        return HttpResponse(status=401)

    text = (request.POST.get("text") or "").strip()
    team_id = request.POST.get("team_id", "")
    user_id = request.POST.get("user_id", "")

    # /tuckit connect is the only subcommand this integration supports. The
    # button in the ephemeral reply to a failed mention is the primary path
    # to linking an account; this is only a second way in for someone who
    # already knows the slash command exists.
    if text != "connect":
        return JsonResponse({
            "response_type": "ephemeral",
            "text": "The only command I understand is `/tuckit connect`.",
        })

    install = SlackInstall.objects.filter(team_id=team_id).first()
    if install is None:
        return JsonResponse({
            "response_type": "ephemeral",
            "text": "This Slack workspace is not connected to a tuckit org yet.",
        })

    connect_url = request.build_absolute_uri(
        f"{reverse('web:slack_connect_begin')}?{urlencode({'state': connect_state(install, user_id)})}"
    )
    return JsonResponse({
        "response_type": "ephemeral",
        "blocks": connect_blocks(connect_url),
    })
