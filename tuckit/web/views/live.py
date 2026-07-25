from django.http import HttpResponse, JsonResponse

from tuckit.core.services.activity import events_since, latest_activity_id, parent_slice_ids


def live(request):
    """Poll target: cheap org-scoped activity cursor. 204 when nothing is newer
    than `since`; otherwise the new events + the advanced cursor. request.org is
    set by TenantMiddleware (membership already enforced)."""
    org = request.org
    try:
        since = int(request.GET.get("since", 0))
    except (TypeError, ValueError):
        since = 0
    if latest_activity_id(org) <= since:
        return HttpResponse(status=204)
    rows = events_since(org, since)
    # What happened vs. what to highlight are not the same thing. A bite is never
    # rendered as its own element on a live-refresh screen — it surfaces as the
    # parent slice's bite progress — so a bite event points the poller at that
    # slice. Everything else highlights itself and carries no highlight_* keys
    # (the client falls back to target_*). One extra query, only when bites moved.
    owning_slice = parent_slice_ids([e.target_id for e in rows if e.target_type == "bite"])
    events = []
    for e in rows:
        event = {
            "id": e.id,
            "actor": e.actor,
            "verb": e.verb,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "target_label": e.target_label,
        }
        if e.target_type == "bite" and e.target_id in owning_slice:
            event["highlight_type"] = "slice"
            event["highlight_id"] = owning_slice[e.target_id]
        events.append(event)
    # Advance the cursor to the newest event actually DELIVERED, not a max read
    # before the fetch: an event inserted between the two reads is included in
    # `events` but would be re-delivered next poll (duplicate toast/refresh) if
    # the cursor lagged behind it. `events` is non-empty here (latest > since
    # guarantees at least one qualifying row) and ascending, so [-1] is the max.
    return JsonResponse({"cursor": events[-1]["id"], "events": events})
