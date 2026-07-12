from django.http import Http404, HttpResponse
from django.shortcuts import render

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.areas import get_or_create_triage, create_area, list_areas, rename_area, delete_area, reorder_area
from tuckit.core.services.slices import create_slice, set_slice_area, set_slice_status, list_slices
from tuckit.core.services.resolve import get_area, get_slice
from tuckit.web.auth import get_current_workspace


def capture(request):
    ws = get_current_workspace(request)
    triage = get_or_create_triage(ws)
    create_slice(triage, request.POST["title"], status="idea", source="human")
    # Bundle out-of-band swaps: a confirmation toast, the live count, and an OOB
    # re-render of the Triage list (lands only if that page is open; htmx ignores
    # OOB targets absent from the current page, so one response fits every page).
    return render(request, "web/partials/_capture_result.html", {
        "slices": list(list_slices(triage).prefetch_related("tags")),
        "areas": [a for a in list_areas(ws) if not a.is_triage],
        "statuses": ["idea", "planned", "building", "shipped"],
    })


def triage_list(request):
    ws = get_current_workspace(request)
    triage_area = get_or_create_triage(ws)
    return render(request, "web/triage.html", {
        "slices": list(list_slices(triage_area).prefetch_related("tags")),
        "areas": [a for a in list_areas(ws) if not a.is_triage],
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


def area_rename(request, area_id):
    ws = get_current_workspace(request)
    try:
        area = get_area(ws, area_id)
    except NotFound:
        raise Http404
    try:
        rename_area(area, request.POST.get("name", ""))
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return render(request, "web/partials/_area_row.html", {"a": area})


def area_delete(request, area_id):
    ws = get_current_workspace(request)
    try:
        area = get_area(ws, area_id)
    except NotFound:
        raise Http404
    try:
        delete_area(area)
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return HttpResponse(status=204)  # htmx empties the row via hx-swap="outerHTML"


def area_reorder(request, area_id):
    ws = get_current_workspace(request)
    try:
        area = get_area(ws, area_id)
        before = get_area(ws, int(request.POST["before_id"])) if request.POST.get("before_id") else None
        after = get_area(ws, int(request.POST["after_id"])) if request.POST.get("after_id") else None
    except NotFound:
        raise Http404
    reorder_area(area, before=before, after=after)
    return HttpResponse(status=204)
