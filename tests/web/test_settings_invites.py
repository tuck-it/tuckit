import pytest

from core.models import Invitation, Org, OrgMember, User
from core.services.orgs import create_workspace


@pytest.fixture
def owner_client(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(username="o@a.com", email="o@a.com")
    owner.set_password("pw123456")
    owner.save()
    OrgMember.objects.create(user=owner, org=org, role="owner")
    ws = create_workspace(org, "Board")
    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()
    return client, org


@pytest.mark.django_db
def test_owner_creates_invite_and_sees_link(owner_client):
    client, org = owner_client
    resp = client.post("/settings/invites", {"email": "new@x.com", "role": "member"})
    assert resp.status_code == 200
    inv = Invitation.objects.get(org=org, email="new@x.com")
    assert inv.token.encode() in resp.content  # link shown


@pytest.mark.django_db
def test_cancel_invite(owner_client):
    client, org = owner_client
    resp = client.post("/settings/invites", {"email": "new@x.com", "role": "member"})
    inv = Invitation.objects.get(org=org, email="new@x.com")
    resp = client.post(f"/settings/invites/{inv.id}/cancel")
    assert resp.status_code == 204
    assert not Invitation.objects.filter(id=inv.id).exists()


@pytest.mark.django_db
def test_member_cannot_invite(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    member = User.objects.create(username="m@a.com", email="m@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    ws = create_workspace(org, "Board")
    client.force_login(member)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()
    resp = client.post("/settings/invites", {"email": "new@x.com", "role": "member"})
    assert resp.status_code == 403
