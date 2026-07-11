import pytest

from tuckit.core.models import Invitation, Org, OrgMember, User
from tuckit.core.services.exceptions import InvalidValue, NotFound
from tuckit.core.services.invitations import (
    create_invitation, get_pending_invitation, accept_invitation, register_invited, cancel_invitation,
)


@pytest.fixture
def org_owner(db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(username="o@a.com", email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    return org, owner


@pytest.mark.django_db
def test_create_invitation_pending_with_token(org_owner):
    org, owner = org_owner
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    assert inv.token
    assert inv.accepted_at is None
    assert get_pending_invitation(inv.token) == inv


@pytest.mark.django_db
def test_accept_by_logged_in_matching_email(org_owner):
    org, owner = org_owner
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    user = User.objects.create(username="new@x.com", email="new@x.com")
    member = accept_invitation(token=inv.token, user=user)
    assert member.org == org and member.role == "member"
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_accept_is_single_use(org_owner):
    org, owner = org_owner
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    user = User.objects.create(username="new@x.com", email="new@x.com")
    accept_invitation(token=inv.token, user=user)
    with pytest.raises(NotFound):
        accept_invitation(token=inv.token, user=user)


@pytest.mark.django_db
def test_accept_rejects_mismatched_email(org_owner):
    org, owner = org_owner
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    other = User.objects.create(username="z@z.com", email="z@z.com")
    with pytest.raises(InvalidValue):
        accept_invitation(token=inv.token, user=other)


@pytest.mark.django_db
def test_register_invited_creates_user_and_joins(org_owner):
    org, owner = org_owner
    inv = create_invitation(org=org, email="new@x.com", role="admin", invited_by=owner)
    user, member = register_invited(invitation=inv, password="pw123456")
    assert user.email == "new@x.com"
    assert member.org == org and member.role == "admin"
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_register_invited_rejects_empty_password(org_owner):
    org, owner = org_owner
    inv = create_invitation(org=org, email="new@x.com", role="admin", invited_by=owner)
    with pytest.raises(InvalidValue):
        register_invited(invitation=inv, password="")


@pytest.mark.django_db
def test_accept_invitation_rejects_existing_member(org_owner):
    import secrets

    org, owner = org_owner
    # create_invitation itself blocks inviting an existing member, so build the
    # Invitation directly to simulate a stale/re-sent invite for someone who has
    # since joined.
    inv = Invitation.objects.create(
        org=org, email="o@a.com", role="member", token=secrets.token_urlsafe(32), invited_by=owner
    )
    with pytest.raises(InvalidValue):
        accept_invitation(token=inv.token, user=owner)
    inv.refresh_from_db()
    assert inv.accepted_at is None


@pytest.mark.django_db
def test_create_invitation_rejects_existing_member(org_owner):
    org, owner = org_owner
    with pytest.raises(InvalidValue):
        create_invitation(org=org, email="o@a.com", role="member", invited_by=owner)


@pytest.mark.django_db
def test_cancel_invitation(org_owner):
    org, owner = org_owner
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    cancel_invitation(org=org, invitation_id=inv.id)
    assert not Invitation.objects.filter(id=inv.id).exists()
