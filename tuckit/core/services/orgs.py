from tuckit.core.models import Org, OrgMember, Workspace
from tuckit.core.services.areas import create_area, get_or_create_inbox


def accessible_workspaces(user):
    org_ids = OrgMember.objects.filter(user=user).values_list("org_id", flat=True)
    return (
        Workspace.objects.filter(org_id__in=list(org_ids))
        .select_related("org")
        .order_by("org__name", "name")
    )


def user_can_access_workspace(user, workspace) -> bool:
    return OrgMember.objects.filter(user=user, org_id=workspace.org_id).exists()


def is_org_admin(user, org) -> bool:
    return OrgMember.objects.filter(user=user, org=org, role__in=["owner", "admin"]).exists()


def seat_count(org) -> int:
    return OrgMember.objects.filter(org=org).count()


def _unique_ws_slug(org: Org, name: str) -> str:
    from django.utils.text import slugify

    base = slugify(name)[:100] or "workspace"
    candidate = base
    i = 2
    while Workspace.objects.filter(org=org, slug=candidate).exists():
        suffix = f"-{i}"
        candidate = base[: 100 - len(suffix)] + suffix
        i += 1
    return candidate


def create_workspace(org: Org, name: str, slug: str | None = None) -> Workspace:
    slug = slug or _unique_ws_slug(org, name)
    ws = Workspace.objects.create(org=org, name=name, slug=slug)
    get_or_create_inbox(ws)
    create_area(ws, "Default")
    return ws
