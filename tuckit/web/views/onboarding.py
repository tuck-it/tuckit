from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from tuckit.core.models import ActivityEvent
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.orgs import accessible_workspaces, create_org
from tuckit.core.services.tokens import generate_token
from tuckit.web.auth import get_current_workspace, landing_route


def first_org(request):
    """Standalone page for a logged-in user with no accessible workspace (e.g. a
    createsuperuser account): create a first org so they get a workspace, instead
    of getting stuck at the app root. Login-protected by middleware."""
    if accessible_workspaces(request.user).exists():
        # Already set up — defer to the single landing decision (→ Home).
        name, kwargs = landing_route(request)
        return redirect(name, **kwargs)
    if request.method == "POST":
        try:
            org, ws = create_org(request.user, name=request.POST.get("name", ""))
        except InvalidValue as exc:
            return render(request, "web/first_org.html", {"error": str(exc), "values": request.POST})
        request.session["active_workspace_id"] = ws.id
        return redirect("web:home", org_slug=org.slug, ws_slug=ws.slug)
    return render(request, "web/first_org.html", {"values": {}})


def _agent_baseline(ws) -> int:
    return (
        ActivityEvent.objects.filter(workspace=ws).order_by("-id")
        .values_list("id", flat=True).first() or 0
    )


@require_POST
def connect_key(request):
    ws = get_current_workspace(request)
    if ws is None:
        return redirect("web:root")
    _token, raw = generate_token(ws, "Agent (onboarding)")
    return render(request, "web/partials/_get_started_key.html", {
        "mcp_url": request.build_absolute_uri("/mcp"),
        "raw_token": raw,
        "agent_baseline": _agent_baseline(ws),
    })


def agent_check(request):
    ws = get_current_workspace(request)
    if ws is None:
        return redirect("web:root")
    try:
        since = int(request.GET.get("since", "0"))
    except ValueError:
        since = 0
    ev = (
        ActivityEvent.objects.filter(workspace=ws, actor="agent", id__gt=since)
        .order_by("id").first()
    )
    if ev is None:
        # 200 (not 204 — base.html:42 swaps on 204); re-serve the poller.
        return render(request, "web/partials/_get_started_listen.html", {"agent_baseline": since})
    celebrate = render_to_string("web/partials/_get_started_celebrate.html", {"event": ev}, request=request)
    widget = render_to_string("web/partials/_onboarding_widget.html", {"oob": True}, request=request)
    return HttpResponse(celebrate + widget)
