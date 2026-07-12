from django.shortcuts import render

from tuckit.core.services.state import (
    home_state,
    attention_items,
    roadmap_state,
    in_progress_state,
    recent_activity,
)
from tuckit.web.auth import get_current_workspace


def home(request):
    ws = get_current_workspace(request)
    return render(request, "web/home.html", {
        "workspace": ws,
        "state": home_state(ws) if ws else {},
        "roadmap": roadmap_state(ws) if ws else {},
        "recent_activity": recent_activity(ws) if ws else [],
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
