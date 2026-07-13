from django.db import transaction

from tuckit.core.models import Org, OrgMember, Workspace
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slugs import RESERVED_ORG_SLUGS, RESERVED_WORKSPACE_SLUGS, validate_slug


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

    base = slugify(name)[:32].strip("-") or "workspace"
    if len(base) < 2:
        base = (base + "workspace")[:32]
    if base in RESERVED_WORKSPACE_SLUGS:
        base = f"{base}-ws"
    candidate = base
    i = 2
    while Workspace.objects.filter(org=org, slug=candidate).exists():
        suffix = f"-{i}"
        candidate = base[: 32 - len(suffix)].rstrip("-") + suffix
        i += 1
    return candidate


def create_workspace(org: Org, name: str, slug: str | None = None) -> Workspace:
    name = " ".join((name or "").split())
    if not name:
        raise InvalidValue("워크스페이스 이름을 입력하세요")
    if Workspace.objects.filter(org=org, name__iexact=name).exists():
        raise InvalidValue(f"이미 같은 이름의 워크스페이스가 있습니다: {name}")
    slug = validate_slug(slug, kind="workspace") if slug else _unique_ws_slug(org, name)
    ws = Workspace.objects.create(org=org, name=name, slug=slug)
    get_or_create_triage(ws)
    create_area(ws, "Default")
    return ws


def _unique_org_slug(name: str) -> str:
    from django.utils.text import slugify

    base = slugify(name)[:32].strip("-") or "org"
    if len(base) < 2:
        base = (base + "org")[:32]
    if base in RESERVED_ORG_SLUGS:
        base = f"{base}-org"
    candidate = base
    i = 2
    while Org.objects.filter(slug=candidate).exists():
        suffix = f"-{i}"
        candidate = base[: 32 - len(suffix)].rstrip("-") + suffix
        i += 1
    return candidate


@transaction.atomic
def create_org(user, *, name: str, slug: str | None = None) -> tuple[Org, Workspace]:
    from tuckit.core.services.hooks import run_signup_hook  # local: avoid import cycle

    name = (name or "").strip()
    if not name:
        raise InvalidValue("조직 이름을 입력하세요")
    slug = validate_slug(slug, kind="org") if slug else _unique_org_slug(name)
    if Org.objects.filter(slug=slug).exists():
        raise InvalidValue(f"이미 사용 중인 조직 슬러그입니다: {slug}")
    org = Org.objects.create(name=name, slug=slug)
    OrgMember.objects.create(user=user, org=org, role="owner")
    workspace = create_workspace(org, name)
    run_signup_hook(user=user, org=org)
    return org, workspace


_VALID_ROLES = {"owner", "admin", "member"}


def is_org_owner(user, org) -> bool:
    return OrgMember.objects.filter(user=user, org=org, role="owner").exists()


def rename_org(org: Org, name: str) -> Org:
    name = (name or "").strip()
    if not name:
        raise InvalidValue("조직 이름을 입력하세요")
    org.name = name
    org.save(update_fields=["name"])
    return org


def list_org_members(org: Org):
    return OrgMember.objects.filter(org=org).select_related("user").order_by("created_at")


def _owner_count(org: Org) -> int:
    return OrgMember.objects.filter(org=org, role="owner").count()


def change_member_role(org: Org, *, member: OrgMember, role: str) -> OrgMember:
    if role not in _VALID_ROLES:
        raise InvalidValue(f"알 수 없는 역할: {role}")
    if member.role == "owner" and role != "owner" and _owner_count(org) <= 1:
        raise InvalidValue("마지막 소유자의 역할은 바꿀 수 없습니다")
    member.role = role
    member.save(update_fields=["role"])
    return member


def remove_member(org: Org, *, member: OrgMember) -> None:
    if member.role == "owner":
        raise InvalidValue("소유자는 제거할 수 없습니다 — 먼저 역할을 변경하세요")
    member.delete()


def delete_workspace(workspace: Workspace) -> None:
    if Workspace.objects.filter(org=workspace.org).count() <= 1:
        raise InvalidValue("조직의 마지막 워크스페이스는 삭제할 수 없습니다")
    workspace.delete()


def list_user_orgs(user) -> list[dict]:
    rows = []
    memberships = (
        OrgMember.objects.filter(user=user).select_related("org").order_by("org__name")
    )
    for m in memberships:
        rows.append({
            "org": m.org,
            "role": m.role,
            "workspace_count": Workspace.objects.filter(org=m.org).count(),
        })
    return rows


def leave_org(user, *, org) -> None:
    membership = OrgMember.objects.filter(user=user, org=org).first()
    if membership is None:
        raise InvalidValue("이 조직의 멤버가 아닙니다")
    if membership.role == "owner" and _owner_count(org) <= 1:
        raise InvalidValue("단독 소유자는 나갈 수 없습니다 — 먼저 소유권을 넘기거나 조직을 삭제하세요")
    if OrgMember.objects.filter(user=user).count() <= 1:
        raise InvalidValue("마지막 조직은 나갈 수 없습니다")
    membership.delete()
