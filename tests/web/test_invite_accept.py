import pytest
from django.test import override_settings

from core.models import Org, OrgMember, User
from core.services.invitations import create_invitation


@pytest.fixture
def invite(db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(username="o@a.com", email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    return org, inv


@pytest.mark.django_db
@override_settings(REGISTRATION_OPEN=False)
def test_anon_can_register_via_invite_even_when_closed(client, invite):
    org, inv = invite
    resp = client.post(f"/invite/{inv.token}/", {"password": "pw123456"})
    assert resp.status_code == 302
    user = User.objects.get(email="new@x.com")
    assert OrgMember.objects.filter(user=user, org=org, role="member").exists()


@pytest.mark.django_db
def test_logged_in_matching_email_joins(client, invite):
    org, inv = invite
    user = User.objects.create(username="new@x.com", email="new@x.com")
    user.set_password("pw123456")
    user.save()
    client.force_login(user)
    resp = client.post(f"/invite/{inv.token}/")
    assert resp.status_code == 302
    assert OrgMember.objects.filter(user=user, org=org).exists()


@pytest.mark.django_db
def test_logged_in_mismatched_email_rejected(client, invite):
    org, inv = invite
    other = User.objects.create(username="z@z.com", email="z@z.com")
    other.set_password("pw123456")
    other.save()
    client.force_login(other)
    resp = client.post(f"/invite/{inv.token}/")
    assert resp.status_code == 200  # error shown, not joined
    assert not OrgMember.objects.filter(user=other, org=org).exists()


@pytest.mark.django_db
def test_used_token_shows_invalid(client, invite):
    org, inv = invite
    user = User.objects.create(username="new@x.com", email="new@x.com")
    client.force_login(user)
    client.post(f"/invite/{inv.token}/")  # accept once
    resp = client.get(f"/invite/{inv.token}/")
    assert resp.status_code == 200
    assert b"invalid" in resp.content.lower() or "유효하지".encode() in resp.content
