from django.db import transaction

from tuckit.core.models import Org, OrgMember
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slugs import RESERVED_ORG_SLUGS, validate_slug


def accessible_orgs(user):
    return Org.objects.filter(members__user=user).order_by("name")


def is_org_admin(user, org) -> bool:
    return OrgMember.objects.filter(user=user, org=org, role__in=["owner", "admin"]).exists()


def seat_count(org) -> int:
    return OrgMember.objects.filter(org=org).count()


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
def create_org(user, *, name: str, slug: str | None = None) -> Org:
    from tuckit.core.services.hooks import run_signup_hook  # local: avoid import cycle

    name = (name or "").strip()
    if not name:
        raise InvalidValue("Enter an organization name.")
    slug = validate_slug(slug) if slug else _unique_org_slug(name)
    if Org.objects.filter(slug=slug).exists():
        raise InvalidValue(f"That organization slug is already taken: {slug}")
    org = Org.objects.create(name=name, slug=slug)
    OrgMember.objects.create(user=user, org=org, role="owner")
    run_signup_hook(user=user, org=org)
    return org


_VALID_ROLES = {"owner", "admin", "member"}


def is_org_owner(user, org) -> bool:
    return OrgMember.objects.filter(user=user, org=org, role="owner").exists()


def rename_org(org: Org, name: str, description: str | None = None) -> Org:
    name = (name or "").strip()
    if not name:
        raise InvalidValue("Enter an organization name.")
    org.name = name
    update_fields = ["name"]
    if description is not None:
        org.description = description
        update_fields.append("description")
    org.save(update_fields=update_fields)
    return org


def set_org_key(org: Org, raw: str) -> Org:
    """Change the org's ref prefix. Every displayed ref follows immediately —
    refs are derived, not stored — which is the point and also why the settings
    row warns that older refs stop resolving."""
    from tuckit.core.services.keys import validate_key

    key = validate_key(raw)
    if Org.objects.filter(key=key).exclude(pk=org.pk).exists():
        raise InvalidValue(f"'{key}' is already taken by another organization.")
    org.key = key
    org.save(update_fields=["key"])
    return org


def list_org_members(org: Org):
    return OrgMember.objects.filter(org=org).select_related("user").order_by("created_at")


def _owner_count(org: Org) -> int:
    return OrgMember.objects.filter(org=org, role="owner").count()


def change_member_role(org: Org, *, member: OrgMember, role: str) -> OrgMember:
    if role not in _VALID_ROLES:
        raise InvalidValue(f"Unknown role: {role}")
    if member.role == "owner" and role != "owner" and _owner_count(org) <= 1:
        raise InvalidValue("Can't change the last owner's role.")
    member.role = role
    member.save(update_fields=["role"])
    return member


def remove_member(org: Org, *, member: OrgMember) -> None:
    if member.role == "owner":
        raise InvalidValue("The owner can't be removed — change their role first.")
    member.delete()


def list_user_orgs(user) -> list[dict]:
    rows = []
    memberships = (
        OrgMember.objects.filter(user=user).select_related("org").order_by("org__name")
    )
    for m in memberships:
        rows.append({
            "org": m.org,
            "role": m.role,
        })
    return rows


def leave_org(user, *, org) -> None:
    membership = OrgMember.objects.filter(user=user, org=org).first()
    if membership is None:
        raise InvalidValue("You're not a member of this organization.")
    if membership.role == "owner" and _owner_count(org) <= 1:
        raise InvalidValue("The sole owner can't leave — transfer ownership or delete the org first.")
    if OrgMember.objects.filter(user=user).count() <= 1:
        raise InvalidValue("You can't leave your last organization.")
    membership.delete()
