import json
import logging
import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tuckit.core.services.orgs import is_org_admin
from tuckit.integrations.slack.api import SlackApiError, exchange_oauth_code
from tuckit.integrations.slack.models import SlackEvent, SlackInstall
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
            SlackEvent.objects.create(event_id=event_id)
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
                lambda: enqueue(job_name, {"team_id": payload.get("team_id", ""), "event": event})
            )
    except IntegrityError:
        # The retry, or its twin racing the original. Already handled.
        return HttpResponse(status=200)

    return HttpResponse(status=200)


# --- Install OAuth flow ---
#
# Everything the bot needs and nothing else. users:read.email,
# message.channels, message.im and reactions:write are deliberately absent —
# see the slice constraints before adding to this list.
BOT_SCOPES = [
    "app_mentions:read", "chat:write", "channels:history", "groups:history",
    "links:read", "links:write", "users:read", "commands",
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
