"""Guards for TP-104: a membership ends without erasing what the person did.

The failure mode this file exists for is a call site nobody updated, so the
authorization gates are enumerated rather than sampled. A test that only checks
`remove_member` stamps `ended_at` would pass while a removed member still had
the run of the org.

It also pins the two pieces of Django behaviour the fail-closed design rests
on, because they differ from each other in a way that is easy to assume wrong:
a related manager honours the default manager, a relation traversal does not.
"""

import pytest

from tuckit.core.models import Org, OrgMember, Slice, User
from tuckit.core.services.exceptions import InvalidValue, NotFound
from tuckit.core.services.invitations import accept_invitation, create_invitation
from tuckit.core.services.members import resolve_member
from tuckit.core.services.orgs import (
    accessible_orgs,
    change_member_role,
    is_org_admin,
    is_org_owner,
    leave_org,
    list_org_members,
    list_user_orgs,
    remove_member,
    seat_count,
)
from tuckit.core.services.slices import create_slice


@pytest.fixture
def acme(db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="owner@a.com")
    leaver = User.objects.create(email="leaver@a.com")
    om_owner = OrgMember.objects.create(user=owner, org=org, role="owner")
    om_leaver = OrgMember.objects.create(user=leaver, org=org, role="member")
    return org, om_owner, om_leaver


# --- the Django behaviour the design depends on ---------------------------


@pytest.mark.django_db
def test_default_manager_hides_an_ended_membership(acme):
    org, _, om_leaver = acme
    remove_member(org, member=om_leaver)

    assert not OrgMember.objects.filter(pk=om_leaver.pk).exists()
    assert OrgMember.all_objects.filter(pk=om_leaver.pk).exists()


@pytest.mark.django_db
def test_related_manager_hides_an_ended_membership(acme):
    """org.members is built from the default manager class, so it filters."""
    org, _, om_leaver = acme
    remove_member(org, member=om_leaver)

    assert not org.members.filter(pk=om_leaver.pk).exists()


@pytest.mark.django_db
def test_relation_traversal_does_not_apply_the_default_manager(acme):
    """The trap accessible_orgs() has to work around.

    A traversal inside filter() compiles to a JOIN against the raw table and
    ignores the related model's manager entirely. Anything relying on the
    fail-closed manager to cover a `members__…` lookup is silently open, which
    is why orgs.py spells the ended_at condition out.
    """
    org, _, om_leaver = acme
    leaver = om_leaver.user
    remove_member(org, member=om_leaver)

    assert Org.objects.filter(members__user=leaver).exists()
    assert not Org.objects.filter(
        members__user=leaver, members__ended_at__isnull=True
    ).exists()


@pytest.mark.django_db
def test_forward_fk_still_resolves_an_ended_membership(acme):
    """base_manager_name keeps history readable: the gate filters, the record does not."""
    org, _, om_leaver = acme
    s = create_slice(org, area=None, title="Written before leaving")
    s.created_by = om_leaver
    s.save(update_fields=["created_by"])
    remove_member(org, member=om_leaver)

    assert Slice.objects.get(pk=s.pk).created_by.user.email == "leaver@a.com"


# --- ending a membership --------------------------------------------------


@pytest.mark.django_db
def test_remove_member_ends_instead_of_deleting(acme):
    org, _, om_leaver = acme
    remove_member(org, member=om_leaver)

    om_leaver.refresh_from_db()
    assert om_leaver.ended_at is not None
    assert om_leaver.is_active is False


@pytest.mark.django_db
def test_leave_org_ends_instead_of_deleting(acme):
    org, _, om_leaver = acme
    other = Org.objects.create(name="Other", slug="other")
    OrgMember.objects.create(user=om_leaver.user, org=other, role="member")

    leave_org(om_leaver.user, org=org)

    om_leaver.refresh_from_db()
    assert om_leaver.ended_at is not None


@pytest.mark.django_db
def test_ending_clears_assignments_but_keeps_authorship(acme):
    org, _, om_leaver = acme
    s = create_slice(org, area=None, title="Theirs")
    s.assignee = om_leaver
    s.created_by = om_leaver
    s.save(update_fields=["assignee", "created_by"])

    remove_member(org, member=om_leaver)

    s.refresh_from_db()
    assert s.assignee is None, "work must not stay assigned to someone who left"
    assert s.created_by_id == om_leaver.pk, "authorship is the thing this slice preserves"


# --- every authorization gate, enumerated ---------------------------------


@pytest.mark.django_db
def test_every_authorization_gate_refuses_an_ended_member(acme):
    org, _, om_leaver = acme
    leaver = om_leaver.user
    # Owner role so the owner/admin gates are genuinely exercised rather than
    # passing because they were False all along, and a second org so the
    # last-organization guard does not block the departure itself.
    change_member_role(org, member=om_leaver, role="owner")
    other = Org.objects.create(name="Other", slug="other")
    OrgMember.objects.create(user=leaver, org=other, role="member")

    # Each gate is (name, callable) so a new gate is one line to cover.
    gates = {
        "is_org_admin": lambda: is_org_admin(leaver, org),
        "is_org_owner": lambda: is_org_owner(leaver, org),
        "membership lookup (middleware / web.auth / oauth consent)":
            lambda: OrgMember.objects.filter(user=leaver, org=org).exists(),
        "accessible_orgs (org switcher, default-org fallback)":
            lambda: org in list(accessible_orgs(leaver)),
        "list_user_orgs": lambda: any(r["org"] == org for r in list_user_orgs(leaver)),
        "list_org_members": lambda: om_leaver in list(list_org_members(org)),
    }

    before = {name: gate() for name, gate in gates.items()}
    assert all(before.values()), f"fixture is not exercising the gates: {before}"

    leave_org(leaver, org=org)

    after = {name: gate() for name, gate in gates.items()}
    assert not any(after.values()), f"these still admit an ended member: {after}"


@pytest.mark.django_db
def test_ended_member_cannot_be_resolved_as_an_assignee(acme):
    org, _, om_leaver = acme
    assert resolve_member(org, "leaver@a.com") == om_leaver

    remove_member(org, member=om_leaver)

    with pytest.raises(NotFound):
        resolve_member(org, "leaver@a.com")


@pytest.mark.django_db
def test_ended_member_gets_404_on_the_org_pages(client, acme):
    org, _, om_leaver = acme
    client.force_login(om_leaver.user)
    assert client.get(f"/{org.slug}/").status_code == 200

    remove_member(org, member=om_leaver)

    assert client.get(f"/{org.slug}/").status_code == 404


@pytest.mark.django_db
def test_ended_member_frees_the_seat(acme):
    org, _, om_leaver = acme
    assert seat_count(org) == 2

    remove_member(org, member=om_leaver)

    assert seat_count(org) == 1, "a departed member must not hold a paid seat forever"


# --- owner and last-org guards must count active rows only ----------------


@pytest.mark.django_db
def test_owner_guard_ignores_an_ended_owner(acme):
    """An owner who left must not keep the org's last live owner demotable."""
    org, om_owner, om_leaver = acme
    change_member_role(org, member=om_leaver, role="owner")
    other = Org.objects.create(name="Other", slug="other")
    OrgMember.objects.create(user=om_leaver.user, org=other, role="member")
    leave_org(om_leaver.user, org=org)  # ended owner; one live owner remains

    # Counting the ended row would make _owner_count 2 and let this through,
    # leaving the org with nobody who can administer it.
    with pytest.raises(InvalidValue):
        change_member_role(org, member=om_owner, role="member")


@pytest.mark.django_db
def test_last_org_guard_ignores_an_ended_membership(acme):
    org, _, om_leaver = acme
    other = Org.objects.create(name="Other", slug="other")
    om_other = OrgMember.objects.create(user=om_leaver.user, org=other, role="member")
    leave_org(om_leaver.user, org=other)
    assert om_other  # left, so acme is now their only live org

    with pytest.raises(InvalidValue):
        leave_org(om_leaver.user, org=org)


# --- rejoining ------------------------------------------------------------


@pytest.mark.django_db
def test_rejoin_resurrects_the_same_membership(acme):
    org, om_owner, om_leaver = acme
    remove_member(org, member=om_leaver)

    inv = create_invitation(
        org=org, email="leaver@a.com", role="admin", invited_by=om_owner.user
    )
    member = accept_invitation(token=inv.token, user=om_leaver.user)

    assert member.pk == om_leaver.pk, "a rejoin must not open a second membership"
    assert OrgMember.all_objects.filter(user=om_leaver.user, org=org).count() == 1
    assert member.ended_at is None
    assert member.role == "admin", "the role comes from the new invitation"


@pytest.mark.django_db
def test_rejoin_does_not_deliver_the_time_they_were_away(acme):
    org, om_owner, om_leaver = acme
    om_leaver.home_seen_at = om_leaver.created_at
    om_leaver.save(update_fields=["home_seen_at"])
    remove_member(org, member=om_leaver)

    inv = create_invitation(
        org=org, email="leaver@a.com", role="member", invited_by=om_owner.user
    )
    member = accept_invitation(token=inv.token, user=om_leaver.user)

    assert member.home_seen_at is None, "NULL is badge-nothing; a returner starts clean"


@pytest.mark.django_db
def test_someone_who_left_can_be_invited_back(acme):
    org, om_owner, om_leaver = acme
    remove_member(org, member=om_leaver)

    inv = create_invitation(
        org=org, email="leaver@a.com", role="member", invited_by=om_owner.user
    )
    assert inv.pk


@pytest.mark.django_db
def test_an_active_member_still_cannot_be_re_invited(acme):
    org, om_owner, _ = acme

    with pytest.raises(InvalidValue):
        create_invitation(
            org=org, email="leaver@a.com", role="member", invited_by=om_owner.user
        )


@pytest.mark.django_db
def test_rejoining_keeps_their_old_work_attributed(acme):
    org, om_owner, om_leaver = acme
    s = create_slice(org, area=None, title="From the first stint")
    s.created_by = om_leaver
    s.save(update_fields=["created_by"])
    remove_member(org, member=om_leaver)

    inv = create_invitation(
        org=org, email="leaver@a.com", role="member", invited_by=om_owner.user
    )
    member = accept_invitation(token=inv.token, user=om_leaver.user)

    s.refresh_from_db()
    assert s.created_by_id == member.pk, "one person, one thread across leave and return"
