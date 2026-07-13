from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import render

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.resolve import get_slice
from tuckit.core.services.slices import set_slice_status, reorder_slice, grouped_slices
from tuckit.core.services.state import roadmap_board_view
from tuckit.web.auth import get_current_workspace


def slice_move(request, slice_id):
    ws = get_current_workspace(request)
    try:
        slice_ = get_slice(ws, slice_id)
    except NotFound:
        raise Http404

    before = after = None
    if request.POST.get("before_id"):
        try: before = get_slice(ws, int(request.POST["before_id"]))
        except NotFound: raise Http404
    if request.POST.get("after_id"):
        try: after = get_slice(ws, int(request.POST["after_id"]))
        except NotFound: raise Http404

    status = request.POST.get("status")

    with transaction.atomic():
        if status and status != slice_.status:
            try:
                set_slice_status(slice_, status)
            except InvalidValue as e:
                return HttpResponse(str(e), status=400)
        if before is not None or after is not None:
            reorder_slice(slice_, before=before, after=after)

    if request.headers.get("HX-Request"):
        # The workspace-wide Board tab re-renders every area; the area page's
        # board re-renders just that area. Drag-drop ignores this response
        # (SortableJS updates optimistically) — only the card's <select> uses it.
        if request.GET.get("scope") == "workspace":
            board = roadmap_board_view(ws)
            return render(request, "web/partials/_board.html", {
                "groups": board["groups"],
                "show_area": True,
                "board_scope": "workspace",
                "shipped_total": board["shipped_total"],
                "shipped_hidden": board["shipped_hidden"],
            })
        groups = grouped_slices(slice_.area)
        return render(request, "web/partials/_board.html", {"groups": groups})
    return HttpResponse(status=204)
