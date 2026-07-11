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
    return {"areas": [a for a in list_areas(ws) if not a.is_inbox]}


def inbox_count(request):
    """Expose the workspace's active (non-dropped) inbox Slice count to every
    template so the sidebar can show a muted count badge next to 인박스."""
    from tuckit.core.models import Area, Slice

    ws = get_current_workspace(request)
    if not ws:
        return {}
    inbox = Area.objects.filter(workspace=ws, is_inbox=True).first()
    n = Slice.objects.filter(area=inbox).exclude(status="dropped").count() if inbox else 0
    return {"inbox_count": n}


def switchable_workspaces(request):
    """Expose the user's accessible workspaces (across all their orgs) to every
    template so the sidebar switcher can list them, regardless of whether the
    current view happens to pass workspace data itself."""
    if not request.user.is_authenticated:
        return {"switchable_workspaces": []}
    return {"switchable_workspaces": list(accessible_workspaces(request.user))}
