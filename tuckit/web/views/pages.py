from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from tuckit.core.services.state import (
    home_state,
    attention_items,
    roadmap_state,
    in_progress_state,
    recent_activity,
)
from tuckit.core.services.onboarding import onboarding_state
from tuckit.web.auth import get_current_workspace


def home(request):
    ws = get_current_workspace(request)
    ob = onboarding_state(ws) if ws else None
    show_get_started = bool(ws and not ws.onboarding_dismissed and ob and not ob.done)
    return render(request, "web/home.html", {
        "workspace": ws,
        "state": home_state(ws) if ws else {},
        "roadmap": roadmap_state(ws) if ws else {},
        "recent_activity": recent_activity(ws) if ws else [],
        "onboarding": ob,
        "show_get_started": show_get_started,
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
    return render(request, "web/roadmap.html", {
        "state": roadmap_state(ws) if ws else {},
    })


def activity(request):
    ws = get_current_workspace(request)
    return render(request, "web/activity.html", {
        "events": recent_activity(ws, limit=100) if ws else [],
    })


@require_POST
def dismiss_onboarding(request):
    ws = get_current_workspace(request)
    if ws is None:
        return redirect("web:root")
    ws.onboarding_dismissed = True
    ws.save(update_fields=["onboarding_dismissed"])
    return redirect("web:home", org_slug=ws.org.slug, ws_slug=ws.slug)
