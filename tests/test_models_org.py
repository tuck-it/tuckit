import pytest
from django.db import IntegrityError

from tuckit.core.models import Org, OrgMember, Invitation, User


@pytest.mark.django_db
def test_org_and_membership_roundtrip():
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="a@b.com")
    m = OrgMember.objects.create(user=user, org=org, role="owner")
    assert m.role == "owner"
    assert list(org.members.all()) == [m]


@pytest.mark.django_db
def test_orgmember_unique_per_user_org():
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="a@b.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    with pytest.raises(IntegrityError):
        OrgMember.objects.create(user=user, org=org, role="member")


@pytest.mark.django_db
def test_invitation_defaults_pending():
    org = Org.objects.create(name="Acme", slug="acme")
    inv = Invitation.objects.create(org=org, email="x@y.com", role="member", token="tok123")
    assert inv.accepted_at is None


@pytest.mark.django_db
def test_org_has_workspace_fields_with_defaults():
    org = Org.objects.create(name="Acme", slug="acme")
    assert org.description == ""
    assert org.onboarding_dismissed is False
    assert org.onboarding_completed is False
    assert org.shipped_board_mode == "count"
    assert org.shipped_board_limit == 8
    assert org.updated_at is not None


@pytest.mark.django_db
def test_org_updated_at_advances_on_save():
    org = Org.objects.create(name="Acme", slug="acme")
    before = org.updated_at
    org.name = "Acme Inc"
    org.save(update_fields=["name", "updated_at"])
    org.refresh_from_db()
    assert org.updated_at > before


@pytest.mark.django_db
def test_org_member_starts_with_no_home_watermark():
    """home_seen_at is the only state behind "new since you last looked". It
    starts null so a first-ever visit badges nothing — a fresh account seeing
    "10 new" would be noise, not news."""
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="a@example.com", password="x")
    m = OrgMember.objects.create(user=user, org=org, role="owner")

    assert m.home_seen_at is None
