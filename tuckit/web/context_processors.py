from tuckit.core.services.areas import list_areas
from tuckit.core.services.orgs import accessible_workspaces
from tuckit.web.auth import get_current_workspace


def sidebar_areas(request):
    """Make the workspace's non-inbox areas available to every template so the
    sidebar's Areas list (and active-nav highlighting) is consistent across
    all pages, not just the ones whose view happens to pass `areas` itself."""
    ws = get_current_workspace(request)
    if not ws:
        return {}
    return {"areas": [a for a in list_areas(ws) if not a.is_triage]}


def triage_count(request):
    """Expose the workspace's active (non-dropped) triage Slice count to every
    template so the sidebar can show a muted count badge next to Triage."""
    from tuckit.core.models import Area, Slice

    ws = get_current_workspace(request)
    if not ws:
        return {}
    triage = Area.objects.filter(workspace=ws, is_triage=True).first()
    n = Slice.objects.filter(area=triage).exclude(status="dropped").count() if triage else 0
    return {"triage_count": n}


def attention_count(request):
    """Count of items needing attention (stale triage + stalled building), for
    the sidebar Attention badge."""
    from tuckit.core.services.state import attention_items

    ws = get_current_workspace(request)
    if not ws:
        return {}
    return {"attention_count": len(attention_items(ws))}


def in_progress_count(request):
    """Count of actively-worked items (building slices + doing bites), for the
    sidebar In Progress badge."""
    from tuckit.core.models import Bite, Slice

    ws = get_current_workspace(request)
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
    ws = getattr(request, "workspace", None)
    if ws is None and request.user.is_authenticated:
        from tuckit.core.models import OrgMember, Workspace
        from tuckit.core.services.orgs import accessible_workspaces
        ws_id = request.session.get("active_workspace_id")
        if ws_id:
            ws = Workspace.objects.filter(pk=ws_id).select_related("org").first()
            if ws and not OrgMember.objects.filter(user=request.user, org=ws.org).exists():
                ws = None
        if ws is None:
            ws = accessible_workspaces(request.user).select_related("org").first()
    return {"current_workspace": ws} if ws else {}
