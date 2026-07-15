from tuckit.core.services.areas import list_areas
from tuckit.core.services.orgs import accessible_workspaces
from tuckit.web.auth import current_workspace_or_fallback


def sidebar_areas(request):
    """Make the workspace's non-inbox areas available to every template so the
    sidebar's Areas list (and active-nav highlighting) is consistent across
    all pages, not just the ones whose view happens to pass `areas` itself."""
    ws = current_workspace_or_fallback(request)
    if not ws:
        return {}
    return {"areas": [a for a in list_areas(ws) if not a.is_triage]}


def triage_count(request):
    """Expose the workspace's active (non-dropped) triage Slice count to every
    template so the sidebar can show a muted count badge next to Triage."""
    from tuckit.core.models import Area, Slice

    ws = current_workspace_or_fallback(request)
    if not ws:
        return {}
    triage = Area.objects.filter(workspace=ws, is_triage=True).first()
    n = Slice.objects.filter(area=triage).exclude(status="dropped").count() if triage else 0
    return {"triage_count": n}


def attention_count(request):
    """Count of items needing attention (stale triage + stalled building), for
    the sidebar Attention badge."""
    from tuckit.core.services.state import attention_items

    ws = current_workspace_or_fallback(request)
    if not ws:
        return {}
    return {"attention_count": len(attention_items(ws))}


def in_progress_count(request):
    """Count of actively-worked items (building slices + doing bites), for the
    sidebar In Progress badge."""
    from tuckit.core.models import Bite, Slice

    ws = current_workspace_or_fallback(request)
    if not ws:
        return {}
    n = (
        Slice.objects.filter(
            area__workspace=ws, area__is_triage=False, status="building"
        ).count()
        + Bite.objects.filter(
            slice__area__workspace=ws, slice__area__is_triage=False, status="doing"
        ).count()
    )
    return {"in_progress_count": n}


def switchable_workspaces(request):
    """Expose the user's accessible workspaces (across all their orgs) to every
    template so the sidebar switcher can list them, regardless of whether the
    current view happens to pass workspace data itself."""
    if not request.user.is_authenticated:
        return {"switchable_workspaces": []}
    workspaces = sorted(
        accessible_workspaces(request.user),
        key=lambda w: (w.org.name, w.name),
    )
    return {"switchable_workspaces": workspaces}


def current_workspace(request):
    """Workspace used for sidebar chrome. Prefers the request's tenant workspace; on
    non-tenant pages (settings/account) falls back to the session/first workspace so the
    sidebar switcher and nav still resolve. Access control is NOT done here — it lives in
    TenantMiddleware."""
    ws = current_workspace_or_fallback(request)
    return {"current_workspace": ws} if ws else {}


def auth_chrome(request):
    """Expose auth-screen chrome to every template: whether self-service
    registration is open (controls the login→signup cross-link) and the optional
    marketing-site URL (makes the auth-card wordmark a link home). Read from
    settings per request so tests can override them."""
    from django.conf import settings

    return {
        "registration_open": settings.REGISTRATION_OPEN,
        "marketing_url": getattr(settings, "TUCKIT_MARKETING_URL", "") or "",
    }


def onboarding(request):
    """Expose onboarding state to every template so the floating Get-started
    widget renders on all pages — and make completion sticky so deleting an
    Area after finishing never resurrects the checklist."""
    from tuckit.core.services.onboarding import onboarding_state
    from tuckit.core.models import ActivityEvent

    ws = current_workspace_or_fallback(request)
    if not ws or ws.onboarding_completed or ws.onboarding_dismissed:
        return {}
    state = onboarding_state(ws)
    if state.done and not ws.onboarding_completed:
        ws.onboarding_completed = True
        ws.save(update_fields=["onboarding_completed"])
    show = not ws.onboarding_dismissed and not ws.onboarding_completed and not state.done
    baseline = (
        ActivityEvent.objects.filter(workspace=ws).order_by("-id")
        .values_list("id", flat=True).first() or 0
    )
    return {
        "onboarding": state,
        "show_get_started": show,
        "onboarding_mcp_url": request.build_absolute_uri("/mcp"),
        "onboarding_agent_baseline": baseline,
    }
