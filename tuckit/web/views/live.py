from django.http import HttpResponse, JsonResponse

from tuckit.core.services.activity import events_since, latest_activity_id


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
    events = [
        {
            "id": e.id,
            "source": e.source,
            "member": (e.member.user.email if e.member_id else None),
            "verb": e.verb,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "target_label": e.target_label,
        }
        for e in rows
    ]
    # Advance the cursor to the newest event actually DELIVERED, not a max read
    # before the fetch: an event inserted between the two reads is included in
    # `events` but would be re-delivered next poll (duplicate toast/refresh) if
    # the cursor lagged behind it. `events` is non-empty here (latest > since
    # guarantees at least one qualifying row) and ascending, so [-1] is the max.
    return JsonResponse({"cursor": events[-1]["id"], "events": events})
