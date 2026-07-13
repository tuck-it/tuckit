from tuckit.core.models import Workspace


def get_current_workspace(request) -> Workspace | None:
    """The workspace resolved for THIS request by TenantMiddleware (strict; used for
    access + view logic). None on non-tenant pages (auth/account/root)."""
    return getattr(request, "workspace", None)
