from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from tuckit.core.services.state import (
    home_state,
    attention_items,
    roadmap_state,
    roadmap_board_view,
    ROADMAP_STATUS_KEYS,
    in_progress_state,
    recent_activity,
    cap_shipped,
)
from tuckit.core.services.onboarding import onboarding_state
from tuckit.web.auth import get_current_workspace


def home(request):
    ws = get_current_workspace(request)
    ob = onboarding_state(ws) if ws else None
    show_get_started = bool(ws and not ws.onboarding_dismissed and ob and not ob.done)
    state = home_state(ws) if ws else {}
    shipped_total = shipped_hidden = 0
    if ws:
        visible, shipped_total = cap_shipped(ws, state.get("shipped", []))
        shipped_hidden = shipped_total - len(visible)
        state = {**state, "shipped": visible}
    return render(request, "web/home.html", {
        "workspace": ws,
        "state": state,
        "in_progress": in_progress_state(ws) if ws else {"slices": [], "bites": []},
        "roadmap": roadmap_state(ws) if ws else {},
        "recent_activity": recent_activity(ws) if ws else [],
        "onboarding": ob,
        "show_get_started": show_get_started,
        "shipped_total": shipped_total,
        "shipped_hidden": shipped_hidden,
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


def activity(request):
    ws = get_current_workspace(request)
    events = recent_activity(ws, limit=100) if ws else []
    is_panel = request.GET.get("panel") == "1" and request.headers.get("HX-Request")
    template = "web/partials/_activity_panel.html" if is_panel else "web/activity.html"
    return render(request, template, {"events": events})


@require_POST
def dismiss_onboarding(request):
    ws = get_current_workspace(request)
    if ws is None:
        return redirect("web:root")
    ws.onboarding_dismissed = True
    ws.save(update_fields=["onboarding_dismissed"])
    return redirect("web:home", org_slug=ws.org.slug, ws_slug=ws.slug)
