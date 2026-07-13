from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from tuckit.core.models import ActivityEvent
from tuckit.core.services.tokens import generate_token
from tuckit.web.auth import get_current_workspace


def welcome(request):
    ws = get_current_workspace(request)
    return render(request, "web/welcome.html", {
        "mcp_url": request.build_absolute_uri("/mcp"),
        "workspace": ws,
        "raw_token": None,
        "baseline": (
            ActivityEvent.objects.filter(workspace=ws).order_by("-id")
            .values_list("id", flat=True).first() or 0
        ),
    })


@require_POST
def welcome_generate_key(request):
    ws = get_current_workspace(request)
    _token, raw = generate_token(ws, "Agent (onboarding)")
    return render(request, "web/partials/_welcome_key.html", {
        "mcp_url": request.build_absolute_uri("/mcp"),
        "raw_token": raw,
    })


def welcome_agent_check(request):
    ws = get_current_workspace(request)
    try:
        since = int(request.GET.get("since", "0"))
    except ValueError:
        since = 0
    ev = (
        ActivityEvent.objects.filter(workspace=ws, actor="agent", id__gt=since)
        .order_by("id").first()
    )
    if ev is None:
        return HttpResponse(status=204)
    return render(request, "web/partials/_welcome_celebrate.html", {"event": ev})
