import pytest

from tuckit.core.models import Invitation, Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


def _login(client, user, ws):
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()


@pytest.fixture
def org_ctx(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(username="o@a.com", email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    member = User.objects.create(username="m@a.com", email="m@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    ws = create_workspace(org, "Board")
    return client, org, owner, member, ws


@pytest.mark.django_db
def test_org_page_lists_members_and_workspaces(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner, ws)
    resp = client.get("/settings/org")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Acme" in body
    assert "o@a.com" in body and "m@a.com" in body
    assert "Board" in body


@pytest.mark.django_db
def test_org_page_requires_login(client, db):
    resp = client.get("/settings/org")
    assert resp.status_code in (302, 403)


@pytest.mark.django_db
def test_owner_renames_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner, ws)
    resp = client.post("/settings/org/rename", {"name": "Beta"})
    assert resp.status_code == 200
    org.refresh_from_db()
    assert org.name == "Beta"


@pytest.mark.django_db
def test_member_cannot_rename_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, member, ws)
    resp = client.post("/settings/org/rename", {"name": "Beta"})
    assert resp.status_code == 403
    org.refresh_from_db()
    assert org.name == "Acme"


@pytest.mark.django_db
def test_owner_changes_member_role(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner, ws)
    om = OrgMember.objects.get(org=org, user=member)
    resp = client.post(f"/settings/org/members/{om.id}/role", {"role": "admin"})
    assert resp.status_code == 200
    om.refresh_from_db()
    assert om.role == "admin"


@pytest.mark.django_db
def test_admin_cannot_change_role(org_ctx):
    client, org, owner, member, ws = org_ctx
    # promote member to admin first (as owner), then act as that admin
    OrgMember.objects.filter(org=org, user=member).update(role="admin")
    _login(client, member, ws)
    om_owner = OrgMember.objects.get(org=org, user=owner)
    resp = client.post(f"/settings/org/members/{om_owner.id}/role", {"role": "member"})
    assert resp.status_code == 403


@pytest.mark.django_db
def test_admin_removes_member(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner, ws)
    om = OrgMember.objects.get(org=org, user=member)
    resp = client.post(f"/settings/org/members/{om.id}/remove")
    assert resp.status_code == 204
    assert not OrgMember.objects.filter(id=om.id).exists()


@pytest.mark.django_db
def test_cannot_remove_member_of_other_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    other = Org.objects.create(name="Other", slug="other")
    stranger = User.objects.create(username="s@s.com", email="s@s.com")
    om_other = OrgMember.objects.create(user=stranger, org=other, role="member")
    _login(client, owner, ws)
    resp = client.post(f"/settings/org/members/{om_other.id}/remove")
    assert resp.status_code == 404
    assert OrgMember.objects.filter(id=om_other.id).exists()


from tuckit.core.models import Org as OrgModel  # alias to avoid fixture shadow


@pytest.mark.django_db
def test_owner_deletes_org_when_has_another(org_ctx):
    client, org, owner, member, ws = org_ctx
    # owner also belongs to a second org, so deleting the first is allowed
    other = OrgModel.objects.create(name="Personal", slug="personal")
    OrgMember.objects.create(user=owner, org=other, role="owner")
    create_workspace(other, "Home")
    _login(client, owner, ws)
    resp = client.post("/settings/org/delete")
    assert resp.status_code == 302
    assert not OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_cannot_delete_last_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner, ws)
    resp = client.post("/settings/org/delete")
    assert resp.status_code == 400
    assert OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_member_cannot_delete_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, member, ws)
    resp = client.post("/settings/org/delete")
    assert resp.status_code == 403
    assert OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_org_page_shows_invite_form_and_pending(org_ctx):
    client, org, owner, member, ws = org_ctx
    Invitation.objects.create(org=org, email="pending@x.com", role="member", token="tok-abc")
    _login(client, owner, ws)
    body = client.get("/settings/org").content.decode()
    assert "web:invite_create" not in body            # url resolved, not literal
    assert 'hx-post="/settings/invites"' in body       # invite form present on org page
    assert "pending@x.com" in body                     # pending invite listed
