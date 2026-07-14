from django.http import Http404
from django.shortcuts import render

from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.resolve import get_area_by_slug, get_slice
from tuckit.core.services.slices import grouped_slices
from tuckit.web.auth import get_current_workspace
from tuckit.web.panel import slice_panel_context


def area_view(request, slug):
    ws = get_current_workspace(request)
    try:
        area = get_area_by_slug(ws, slug)
    except NotFound:
        raise Http404
    groups = grouped_slices(area)
    has_any_slice = any(items for _, items in groups)
    return render(request, "web/area.html", {
        "area": area,
        "groups": groups,
        "has_any_slice": has_any_slice,
        "view": request.GET.get("view", "list"),
    })


def slice_detail(request, slice_id):
    ws = get_current_workspace(request)
    try:
        slice_ = get_slice(ws, slice_id)
    except NotFound:
        raise Http404
    is_panel = request.GET.get("panel") == "1" and bool(request.headers.get("HX-Request"))
    ctx = slice_panel_context(slice_, is_panel=is_panel)
    template = "web/partials/_slice_panel.html" if is_panel else "web/slice_detail.html"
    return render(request, template, ctx)
