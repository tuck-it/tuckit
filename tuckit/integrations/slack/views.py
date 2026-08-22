import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tuckit.integrations.slack.models import SlackEvent
from tuckit.integrations.slack.queue import enqueue
from tuckit.integrations.slack.signing import SlackSignatureError, verify_signature

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
