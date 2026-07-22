from django.http import Http404
from django.shortcuts import render

from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.resolve import get_area_by_slug, get_slice
from tuckit.core.services.slices import list_slices
from tuckit.core.services.state import AREA_STATUS_KEYS, area_board_view
from tuckit.web.auth import get_current_org
from tuckit.web.panel import slice_panel_context


def area_view(request, slug):
    org = get_current_org(request)
    try:
        area = get_area_by_slug(org, slug)
    except NotFound:
        raise Http404
    status = request.GET.get("status")
    if status in AREA_STATUS_KEYS:
        # Single-status flat list — the uncapped "view all" / archive surface
        # behind the shipped overflow and Dropped links.
        return render(request, "web/area.html", {
            "area": area,
            "filter_status": status,
            "filter_slices": list(
                list_slices(area, status=status).prefetch_related("tags").order_by("rank")
            ),
        })
    board = area_board_view(area)
    return render(request, "web/area.html", {
        "area": area,
        "groups": board["groups"],
        "has_any_slice": board["has_any_slice"],
        "shipped_total": board["shipped_total"],
        "shipped_hidden": board["shipped_hidden"],
        "dropped_count": board["dropped_count"],
        "focus": request.GET.get("focus", ""),
    })


def slice_detail(request, slice_id):
    org = get_current_org(request)
    try:
        slice_ = get_slice(org, slice_id)
    except NotFound:
        raise Http404
    is_panel = request.GET.get("panel") == "1" and bool(request.headers.get("HX-Request"))
    ctx = slice_panel_context(slice_, is_panel=is_panel)
    ctx["focus"] = request.GET.get("focus", "")
    template = "web/partials/_slice_panel.html" if is_panel else "web/slice_detail.html"
    return render(request, template, ctx)
