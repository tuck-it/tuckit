import pytest

from tuckit.core.models import Area, Org, OrgMember, User, Workspace
from tuckit.core.services.orgs import (
    accessible_workspaces, user_can_access_workspace, is_org_admin, seat_count, create_workspace,
    is_org_owner, rename_org, list_org_members, change_member_role, remove_member, delete_workspace,
    create_org, list_user_orgs, leave_org, _unique_org_slug, _unique_ws_slug,
)
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slugs import validate_slug


@pytest.fixture
def org_with_owner(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    return org, user


@pytest.mark.django_db
def test_create_workspace_sets_up_inbox_only(org_with_owner):
    org, _ = org_with_owner
    ws = create_workspace(org, "Board")
    assert ws.org == org
    assert Area.objects.filter(org=org, is_triage=True).count() == 1
    assert Area.objects.filter(org=org, is_triage=False).count() == 0


@pytest.mark.django_db
def test_create_workspace_unique_slug_within_org(org_with_owner):
    org, _ = org_with_owner
    # different names that slugify to the same base ("board") -> slug must dedupe
    a = create_workspace(org, "Board!")
    b = create_workspace(org, "Board?")
    assert a.name != b.name
    assert a.slug != b.slug


@pytest.mark.django_db
def test_access_helpers(org_with_owner):
    org, user = org_with_owner
    ws = create_workspace(org, "Board")
    assert user_can_access_workspace(user, ws) is True
    assert is_org_admin(user, org) is True
    assert seat_count(org) == 1

    outsider = User.objects.create(email="x@x.com")
    assert user_can_access_workspace(outsider, ws) is False
    assert is_org_admin(outsider, org) is False
    assert list(accessible_workspaces(user)) == [ws]
    assert list(accessible_workspaces(outsider)) == []


@pytest.fixture
def org_owner_admin_member(db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="owner@a.com")
    admin = User.objects.create(email="admin@a.com")
    member = User.objects.create(email="member@a.com")
    om_owner = OrgMember.objects.create(user=owner, org=org, role="owner")
    om_admin = OrgMember.objects.create(user=admin, org=org, role="admin")
    om_member = OrgMember.objects.create(user=member, org=org, role="member")
    return org, om_owner, om_admin, om_member


@pytest.mark.django_db
def test_is_org_owner(org_owner_admin_member):
    org, om_owner, om_admin, _ = org_owner_admin_member
    assert is_org_owner(om_owner.user, org) is True
    assert is_org_owner(om_admin.user, org) is False


@pytest.mark.django_db
def test_rename_org(org_with_owner):
    org, _ = org_with_owner
    rename_org(org, "Beta")
    org.refresh_from_db()
    assert org.name == "Beta"


@pytest.mark.django_db
def test_rename_org_rejects_blank(org_with_owner):
    org, _ = org_with_owner
    with pytest.raises(InvalidValue):
        rename_org(org, "   ")


@pytest.mark.django_db
def test_list_org_members_ordered(org_owner_admin_member):
    org, om_owner, om_admin, om_member = org_owner_admin_member
    assert list(list_org_members(org)) == [om_owner, om_admin, om_member]


@pytest.mark.django_db
def test_change_member_role(org_owner_admin_member):
    org, _, om_admin, _ = org_owner_admin_member
    change_member_role(org, member=om_admin, role="member")
    om_admin.refresh_from_db()
    assert om_admin.role == "member"


@pytest.mark.django_db
def test_change_member_role_rejects_bad_role(org_owner_admin_member):
    org, _, om_admin, _ = org_owner_admin_member
    with pytest.raises(InvalidValue):
        change_member_role(org, member=om_admin, role="superadmin")


@pytest.mark.django_db
def test_cannot_demote_last_owner(org_with_owner):
    org, owner = org_with_owner
    om = OrgMember.objects.get(org=org, user=owner)
    with pytest.raises(InvalidValue):
        change_member_role(org, member=om, role="admin")


@pytest.mark.django_db
def test_remove_member(org_owner_admin_member):
    org, _, _, om_member = org_owner_admin_member
    remove_member(org, member=om_member)
    assert not OrgMember.objects.filter(id=om_member.id).exists()


@pytest.mark.django_db
def test_cannot_remove_owner(org_owner_admin_member):
    org, om_owner, _, _ = org_owner_admin_member
    with pytest.raises(InvalidValue):
        remove_member(org, member=om_owner)


@pytest.mark.django_db
def test_delete_workspace_removes_it_and_cascades(org_with_owner):
    """Areas are org-scoped now (workspace=None on create — see task-5-report.md
    Option B fix): get_or_create_triage(org) is idempotent per org, so "Doomed"'s
    seed call finds "Keep"'s existing triage rather than creating its own, and
    no Area carries a `workspace` FK for delete_workspace to cascade through
    anymore. This test now only asserts the workspace row itself is removed
    (and its org-scoped areas are untouched); delete_workspace is dropped
    entirely in Task 10."""
    org, _ = org_with_owner
    keep = create_workspace(org, "Keep")
    doomed = create_workspace(org, "Doomed")
    area_ids = list(Area.objects.filter(org=org).values_list("id", flat=True))
    assert area_ids  # create_workspace seeds the org's inbox
    delete_workspace(doomed)
    assert not Workspace.objects.filter(id=doomed.id).exists()
    assert Area.objects.filter(id__in=area_ids).exists()  # org-scoped, not cascaded
    assert Workspace.objects.filter(id=keep.id).exists()


@pytest.mark.django_db
def test_cannot_delete_last_workspace_in_org(org_with_owner):
    org, _ = org_with_owner
    only = create_workspace(org, "Only")
    with pytest.raises(InvalidValue):
        delete_workspace(only)
    assert Workspace.objects.filter(id=only.id).exists()


@pytest.mark.django_db
def test_create_org_makes_org_owner_and_first_workspace():
    user = User.objects.create(email="u@u.com")
    org, ws = create_org(user, name="Acme Labs")
    assert org.slug == "acme-labs"                       # auto slug from name
    assert OrgMember.objects.filter(user=user, org=org, role="owner").exists()
    assert ws.org == org
    assert Area.objects.filter(org=org, is_triage=True).count() == 1
    assert Area.objects.filter(org=org, is_triage=False).count() == 0


@pytest.mark.django_db
def test_create_org_auto_slug_is_unique():
    user = User.objects.create(email="u@u.com")
    a, _ = create_org(user, name="Dup")
    b, _ = create_org(user, name="Dup")
    assert a.slug != b.slug                               # second gets -2 suffix


@pytest.mark.django_db
def test_create_org_rejects_blank_name():
    user = User.objects.create(email="u@u.com")
    with pytest.raises(InvalidValue):
        create_org(user, name="   ")


@pytest.mark.django_db
def test_create_org_rejects_taken_explicit_slug():
    user = User.objects.create(email="u@u.com")
    create_org(user, name="First", slug="taken")
    with pytest.raises(InvalidValue):
        create_org(user, name="Second", slug="taken")


@pytest.mark.django_db
def test_create_org_runs_signup_hook():
    from django.test import override_settings

    seen = {}

    def _hook(*, user, org):
        seen["ok"] = (user.email, org.slug)

    import tests.test_services_orgs as mod
    mod._hook = _hook
    with override_settings(TUCKIT_SIGNUP_HOOK="tests.test_services_orgs._hook"):
        user = User.objects.create(email="hook@u.com")
        org, ws = create_org(user, name="Hooked")
    assert seen["ok"] == ("hook@u.com", org.slug)
    assert org.pk is not None


@pytest.mark.django_db
def test_list_user_orgs_returns_role_and_workspace_count():
    user = User.objects.create(email="u@u.com")
    org_a, _ = create_org(user, name="Alpha")          # owner, 1 ws
    org_b, _ = create_org(user, name="Beta")           # owner, 1 ws
    Workspace.objects.create(org=org_b, name="Extra", slug="extra")  # Beta now 2 ws
    rows = list_user_orgs(user)
    by_name = {r["org"].name: r for r in rows}
    assert by_name["Alpha"]["role"] == "owner"
    assert by_name["Alpha"]["workspace_count"] == 1
    assert by_name["Beta"]["workspace_count"] == 2
    assert [r["org"].name for r in rows] == ["Alpha", "Beta"]  # ordered by name


@pytest.mark.django_db
def test_list_user_orgs_includes_workspaces():
    from tuckit.core.models import User
    from tuckit.core.services.orgs import create_org, create_workspace, list_user_orgs

    user = User.objects.create(email="w@w.com")
    org, first_ws = create_org(user, name="Acme")
    second_ws = create_workspace(org, "Marketing")

    rows = list_user_orgs(user)
    assert len(rows) == 1
    names = [w.name for w in rows[0]["workspaces"]]
    assert names == sorted([first_ws.name, second_ws.name])


@pytest.mark.django_db
def test_leave_org_removes_membership():
    owner = User.objects.create(email="o@o.com")
    org, _ = create_org(owner, name="Team")            # owner also needs a 2nd org
    create_org(owner, name="Solo")                     # so leaving Team isn't "last org"
    member = User.objects.create(email="m@m.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    create_org(member, name="Members Own")             # member has a 2nd org too
    leave_org(member, org=org)
    assert not OrgMember.objects.filter(user=member, org=org).exists()


@pytest.mark.django_db
def test_leave_org_rejects_non_member():
    stranger = User.objects.create(email="s@s.com")
    other_owner = User.objects.create(email="o@o.com")
    org, _ = create_org(other_owner, name="NotYours")
    create_org(stranger, name="Strangers Own")
    with pytest.raises(InvalidValue):
        leave_org(stranger, org=org)


@pytest.mark.django_db
def test_leave_org_rejects_sole_owner():
    owner = User.objects.create(email="o@o.com")
    org, _ = create_org(owner, name="OnlyOwner")
    create_org(owner, name="Second")                   # not last-org, isolate the sole-owner guard
    with pytest.raises(InvalidValue):
        leave_org(owner, org=org)
    assert OrgMember.objects.filter(user=owner, org=org).exists()


@pytest.mark.django_db
def test_leave_org_rejects_last_org():
    member = User.objects.create(email="m@m.com")
    other_owner = User.objects.create(email="o@o.com")
    org, _ = create_org(other_owner, name="TheOrg")
    OrgMember.objects.create(user=member, org=org, role="member")  # member's ONLY org
    with pytest.raises(InvalidValue):
        leave_org(member, org=org)
    assert OrgMember.objects.filter(user=member, org=org).exists()


@pytest.mark.django_db
def test_create_org_rejects_bad_slug():
    from tuckit.core.models import User
    u = User.objects.create(email="x@y.com")
    with pytest.raises(InvalidValue):
        create_org(u, name="Acme", slug="Bad Slug!")


@pytest.mark.django_db
def test_create_org_rejects_reserved_slug():
    from tuckit.core.models import User
    u = User.objects.create(email="x2@y.com")
    with pytest.raises(InvalidValue):
        create_org(u, name="Settings Co", slug="settings")


@pytest.mark.django_db
def test_auto_org_slug_avoids_reserved():
    # name "Admin" slugifies to reserved "admin" -> must be escaped
    assert _unique_org_slug("Admin") != "admin"


@pytest.mark.django_db
def test_auto_org_slug_meets_min_length():
    # slugify("A") == "a" (1 char) -> below the 2-char floor unless padded
    slug = _unique_org_slug("A")
    validate_slug(slug, kind="org")  # must not raise
    assert len(slug) >= 2


@pytest.mark.django_db
def test_auto_ws_slug_meets_min_length(org_with_owner):
    org, _ = org_with_owner
    slug = _unique_ws_slug(org, "A")
    validate_slug(slug, kind="workspace")  # must not raise
    assert len(slug) >= 2


@pytest.mark.django_db
def test_auto_org_slug_no_trailing_hyphen_after_truncation():
    # slugify(name) is 37 chars with a hyphen at index 31 -> naive [:32] truncation
    # would cut right after that hyphen, leaving a trailing "-" that fails validate_slug.
    name = "a" * 31 + "-bcdef"
    slug = _unique_org_slug(name)
    validate_slug(slug, kind="org")  # must not raise


@pytest.mark.django_db
def test_auto_ws_slug_no_trailing_hyphen_after_truncation(org_with_owner):
    org, _ = org_with_owner
    name = "a" * 31 + "-bcdef"
    slug = _unique_ws_slug(org, name)
    validate_slug(slug, kind="workspace")  # must not raise


@pytest.mark.django_db
def test_org_name_not_globally_unique():
    from tuckit.core.models import User
    u1 = User.objects.create(email="a@y.com")
    u2 = User.objects.create(email="b@y.com")
    create_org(u1, name="Acme", slug="acme-one")
    # same name, different slug -> allowed
    create_org(u2, name="Acme", slug="acme-two")
    assert Org.objects.filter(name="Acme").count() == 2


@pytest.mark.django_db
def test_workspace_name_unique_per_org():
    org = Org.objects.create(name="Org", slug="org-x")
    create_workspace(org, "Design")
    with pytest.raises(InvalidValue):
        create_workspace(org, "design")  # case-insensitive duplicate
