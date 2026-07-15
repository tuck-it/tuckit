from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from tuckit.core.services.state import (
    home_state,
    attention_items,
    roadmap_state,
    roadmap_board_view,
    ROADMAP_STATUS_KEYS,
    in_progress_state,
    cap_shipped,
    snapshot_today,
)
from tuckit.web.auth import get_current_workspace


def home(request):
    ws = get_current_workspace(request)
    state = home_state(ws) if ws else {}
    metrics = []
    if ws:
        snap = snapshot_today(ws, state)
        _defs = [
            ("Building", "building"),
            ("Backlog", "backlog"),
            ("Shipped this week", "shipped_week"),
            ("Needs attention", "attention"),
        ]
        for label, key in _defs:
            d = snap[key]["delta"]
            metrics.append({
                "label": label,
                "value": snap[key]["value"],
                "delta": d,
                "abs": abs(d) if d is not None else None,
                "dir": None if d is None else ("up" if d > 0 else "down" if d < 0 else "flat"),
            })
    shipped_total = shipped_hidden = 0
    if ws:
        visible, shipped_total = cap_shipped(ws, state.get("shipped", []))
        shipped_hidden = shipped_total - len(visible)
        state = {**state, "shipped": visible}
    building_ct = len(state.get("building", []))
    later_items = state.get("ideas", []) + state.get("someday", [])
    later_ct = len(later_items)
    queued_ct = len(state.get("planned", [])) + later_ct
    return render(request, "web/home.html", {
        "workspace": ws,
        "state": state,
        "building_ct": building_ct,
        "later_items": later_items,
        "later_ct": later_ct,
        "queued_ct": queued_ct,
        "in_progress": in_progress_state(ws) if ws else {"slices": [], "bites": []},
        "roadmap": roadmap_state(ws) if ws else {},
        "shipped_total": shipped_total,
        "shipped_hidden": shipped_hidden,
        "metrics": metrics,
    })


def attention(request):
    ws = get_current_workspace(request)
    return render(request, "web/attention.html", {
        "items": attention_items(ws) if ws else [],
    })


def in_progress(request):
    ws = get_current_workspace(request)
    return render(request, "web/in_progress.html", {
        "state": in_progress_state(ws) if ws else {"slices": [], "bites": []},
    })


def roadmap(request):
    ws = get_current_workspace(request)
    status = request.GET.get("status")
    if ws and status in ROADMAP_STATUS_KEYS:
        # Focused single-status flat list — the "view all" / archive surface.
        state = roadmap_state(ws)
        return render(request, "web/roadmap.html", {
            "filter_status": status,
            "filter_slices": state.get(status, []),
            "show_area": True,
        })

    view = "list" if request.GET.get("view") == "list" else "board"
    board = roadmap_board_view(ws) if ws else {
        "state": {}, "groups": [], "shipped_total": 0, "shipped_hidden": 0,
    }
    return render(request, "web/roadmap.html", {
        "state": board["state"],
        "groups": board["groups"],
        "view": view,
        "has_any_slice": any(v for k, v in board["state"].items() if k != "shipped") or board["shipped_total"] > 0,
        # Board tab spans every area, so surface each slice's area on its card/row.
        "show_area": True,
        "board_scope": "workspace",
        "shipped_total": board["shipped_total"],
        "shipped_hidden": board["shipped_hidden"],
    })


def areas(request):
    ws = get_current_workspace(request)
    cards = []
    if ws:
        from tuckit.core.services.areas import list_areas
        from tuckit.core.models import Slice
        for a in list_areas(ws):
            if a.is_triage:
                continue
            counts = {}
            for s in Slice.objects.filter(area=a).exclude(status="dropped").values_list("status", flat=True):
                counts[s] = counts.get(s, 0) + 1
            cards.append({
                "area": a,
                "total": sum(counts.values()),
                "building": counts.get("building", 0),
                "shipped": counts.get("shipped", 0),
            })
    return render(request, "web/areas.html", {"cards": cards, "is_empty": not cards})


@require_POST
def dismiss_onboarding(request):
    ws = get_current_workspace(request)
    if ws is None:
        return redirect("web:root")
    ws.onboarding_dismissed = True
    ws.save(update_fields=["onboarding_dismissed"])
    return redirect("web:home", org_slug=ws.org.slug, ws_slug=ws.slug)
