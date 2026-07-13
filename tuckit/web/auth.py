from tuckit.core.models import Workspace


def get_current_workspace(request) -> Workspace | None:
    """The workspace resolved for THIS request by TenantMiddleware (strict; used for
    access + view logic). None on non-tenant pages (auth/account/root)."""
    return getattr(request, "workspace", None)


def resolve_fallback_workspace(request) -> Workspace | None:
    """Best-effort workspace for non-tenant pages (e.g. welcome) that still need one:
    prefers the session's active workspace, else the user's first accessible one.
    Membership-checked. None if the user has no accessible workspace."""
    if not request.user.is_authenticated:
        return None
    from tuckit.core.models import OrgMember
    from tuckit.core.services.orgs import accessible_workspaces

    ws_id = request.session.get("active_workspace_id")
    if ws_id:
        ws = Workspace.objects.filter(pk=ws_id).select_related("org").first()
        if ws and OrgMember.objects.filter(user=request.user, org=ws.org).exists():
            return ws
    return accessible_workspaces(request.user).select_related("org").first()
