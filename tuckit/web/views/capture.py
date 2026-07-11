from django.http import Http404, HttpResponse
from django.shortcuts import render

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.areas import get_or_create_inbox, create_area, list_areas
from tuckit.core.services.slices import create_slice, set_slice_area, set_slice_status, list_slices
from tuckit.core.services.resolve import get_area, get_slice
from tuckit.web.auth import get_current_workspace


def capture(request):
    ws = get_current_workspace(request)
    inbox = get_or_create_inbox(ws)
    create_slice(inbox, request.POST["title"], status="idea", source="human")
    # Return an out-of-band swap of the sidebar inbox count instead of a 204 +
    # full-page reload, so rapid capture (Enter, Enter, …) stays snappy and the
    # count updates live. The context processor recomputes inbox_count fresh.
    return render(request, "web/partials/_inbox_count.html", {"oob": True})


def inbox(request):
    ws = get_current_workspace(request)
    inbox_area = get_or_create_inbox(ws)
    return render(request, "web/inbox.html", {
        "slices": list(list_slices(inbox_area).prefetch_related("tags")),
        "areas": [a for a in list_areas(ws) if not a.is_inbox],
        "statuses": ["idea", "planned", "building", "shipped"],
    })


def triage(request, slice_id):
    ws = get_current_workspace(request)
    area_id = request.POST.get("area_id")
    try:
        slice_ = get_slice(ws, slice_id)
        area = get_area(ws, int(area_id)) if area_id else None
    except NotFound:
        raise Http404
    try:
        set_slice_status(slice_, request.POST["status"])
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    if area_id:
        set_slice_area(slice_, area)
    return HttpResponse(status=204)  # htmx removes the row via hx-swap


def area_create(request):
    ws = get_current_workspace(request)
    create_area(ws, request.POST["name"])
    # OOB-swap the sidebar Areas list instead of a full-page reload; the
    # sidebar_areas context processor supplies the refreshed `areas`.
    return render(request, "web/partials/_area_nav.html", {"oob": True})
