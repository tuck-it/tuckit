from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from tuckit.core.models import ActivityEvent
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.orgs import accessible_orgs, create_org
from tuckit.core.services.tokens import generate_token
from tuckit.web.auth import get_current_org


def orgs(request):
    """Every org the user belongs to, plus create. The empty state IS the create
    form — a user with no orgs and a user adding their second one use one screen.
    Absorbs the old standalone first-org page (e.g. for a createsuperuser account
    that would otherwise get stuck at the app root). Login-protected by middleware."""
    if request.method == "POST":
        try:
            org = create_org(request.user, name=request.POST.get("name", ""), slug=request.POST.get("slug", ""))
        except InvalidValue as exc:
            return render(request, "web/orgs.html", {
                "orgs": accessible_orgs(request.user),
                "error": str(exc),
                "values": request.POST,
            })
        request.session["active_org_id"] = org.id
        return redirect("web:home", org_slug=org.slug)
    return render(request, "web/orgs.html", {"orgs": accessible_orgs(request.user)})


def _agent_baseline(org) -> int:
    return (
        ActivityEvent.objects.filter(org=org).order_by("-id")
        .values_list("id", flat=True).first() or 0
    )


@require_POST
def connect_key(request):
    org = get_current_org(request)
    if org is None:
        return redirect("web:root")
    _token, raw = generate_token(org, "Agent (onboarding)")
    return render(request, "web/partials/_get_started_key.html", {
        "mcp_url": request.build_absolute_uri("/mcp"),
        "raw_token": raw,
        "agent_baseline": _agent_baseline(org),
    })


def agent_check(request):
    org = get_current_org(request)
    if org is None:
        return redirect("web:root")
    try:
        since = int(request.GET.get("since", "0"))
    except ValueError:
        since = 0
    ev = (
        ActivityEvent.objects.filter(org=org, actor="agent", id__gt=since)
        .order_by("id").first()
    )
    if ev is None:
        # 200 (not 204 — base.html:42 swaps on 204); re-serve the poller.
        return render(request, "web/partials/_get_started_listen.html", {"agent_baseline": since})
    celebrate = render_to_string("web/partials/_get_started_celebrate.html", {"event": ev}, request=request)
    widget = render_to_string("web/partials/_onboarding_widget.html", {"oob": True}, request=request)
    return HttpResponse(celebrate + widget)
