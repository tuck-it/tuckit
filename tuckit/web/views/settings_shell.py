from django.shortcuts import redirect

from tuckit.core.services.orgs import is_org_admin, is_org_owner


def _ws_in_org(request, org):
    """A workspace belonging to `org` for the settings nav / redirects. Prefer the
    request's tenant workspace (if it's in this org), else the session-active one
    (if in this org), else the org's first workspace. Never returns a workspace
    from a different org — that would 404 under /<org>/settings/workspaces/<ws>/."""
    if org is None:
        return None
    ws = getattr(request, "workspace", None)
    if ws is not None and ws.org_id == org.id:
        return ws
    active_id = request.session.get("active_workspace_id")
    if active_id:
        ws = org.workspaces.filter(pk=active_id).first()
        if ws is not None:
            return ws
    return org.workspaces.order_by("name").first()


def settings_context(request, *, active):
    """Shared context for the settings shell nav. request.org is set by
    TenantMiddleware; the Workspace group targets a workspace *in this org*."""
    org = request.org
    return {
        "nav_org": org,
        "nav_ws": _ws_in_org(request, org),
        "settings_active": active,
        "can_admin": is_org_admin(request.user, org) if org else False,
        "can_owner": is_org_owner(request.user, org) if org else False,
    }


def settings_root(request):
    ws = _ws_in_org(request, request.org)
    if ws is None:  # org with zero workspaces (shouldn't happen — create_org makes one)
        return redirect("web:settings_org_general", org_slug=request.org.slug)
    return redirect("web:settings_ws_general", org_slug=request.org.slug, ws_slug=ws.slug)


def settings_account_root(request):
    return redirect("web:settings_account_profile", org_slug=request.org.slug)
