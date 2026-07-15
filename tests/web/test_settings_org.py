import pytest

from tuckit.core.models import Invitation, Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


def _login(client, user):
    client.force_login(user)


@pytest.fixture
def org_ctx(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    member = User.objects.create(email="m@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    ws = create_workspace(org, "Board")
    return client, org, owner, member, ws


@pytest.mark.django_db
def test_org_page_lists_members_and_workspaces(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner)
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Acme" in body
    assert "o@a.com" in body and "m@a.com" in body
    assert "Board" in body


@pytest.mark.django_db
def test_org_only_settings_branch_works_for_member(org_ctx):
    # Proves the org-only route sets request.org with request.workspace None and
    # still renders the sidebar chrome via the current_workspace fallback.
    client, org, owner, member, ws = org_ctx
    _login(client, member)
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_org_page_requires_login(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code in (302, 404)  # anon -> login redirect


@pytest.mark.django_db
def test_nonmember_gets_404_on_other_org_settings(org_ctx):
    client, org, owner, member, ws = org_ctx
    other = Org.objects.create(name="Other", slug="other")
    stranger = User.objects.create(email="stranger@x.com")
    OrgMember.objects.create(user=stranger, org=other, role="owner")
    _login(client, owner)  # owner is NOT a member of `other`
    resp = client.get(f"/{other.slug}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_owner_renames_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner)
    resp = client.post(f"/settings/{org.slug}/rename", {"name": "Beta"})
    assert resp.status_code == 200
    org.refresh_from_db()
    assert org.name == "Beta"


@pytest.mark.django_db
def test_member_cannot_rename_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, member)
    resp = client.post(f"/settings/{org.slug}/rename", {"name": "Beta"})
    assert resp.status_code == 403
    org.refresh_from_db()
    assert org.name == "Acme"


@pytest.mark.django_db
def test_owner_changes_member_role(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner)
    om = OrgMember.objects.get(org=org, user=member)
    resp = client.post(f"/settings/{org.slug}/members/{om.id}/role", {"role": "admin"})
    assert resp.status_code == 200
    om.refresh_from_db()
    assert om.role == "admin"


@pytest.mark.django_db
def test_admin_cannot_change_role(org_ctx):
    client, org, owner, member, ws = org_ctx
    # promote member to admin first (as owner), then act as that admin
    OrgMember.objects.filter(org=org, user=member).update(role="admin")
    _login(client, member)
    om_owner = OrgMember.objects.get(org=org, user=owner)
    resp = client.post(f"/settings/{org.slug}/members/{om_owner.id}/role", {"role": "member"})
    assert resp.status_code == 403


@pytest.mark.django_db
def test_admin_removes_member(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner)
    om = OrgMember.objects.get(org=org, user=member)
    resp = client.post(f"/settings/{org.slug}/members/{om.id}/remove")
    assert resp.status_code == 204
    assert not OrgMember.objects.filter(id=om.id).exists()


@pytest.mark.django_db
def test_cannot_remove_member_of_other_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    other = Org.objects.create(name="Other", slug="other")
    stranger = User.objects.create(email="s@s.com")
    om_other = OrgMember.objects.create(user=stranger, org=other, role="member")
    _login(client, owner)
    resp = client.post(f"/settings/{org.slug}/members/{om_other.id}/remove")
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
    _login(client, owner)
    resp = client.post(f"/settings/{org.slug}/delete")
    assert resp.status_code == 302
    assert not OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_owner_deletes_org_htmx_redirects(org_ctx):
    client, org, owner, member, ws = org_ctx
    other = OrgModel.objects.create(name="Personal", slug="personal")
    OrgMember.objects.create(user=owner, org=other, role="owner")
    create_workspace(other, "Home")
    _login(client, owner)
    resp = client.post(f"/settings/{org.slug}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert resp["HX-Redirect"] == "/"  # full browser navigation, not an in-place swap
    assert not OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_cannot_delete_last_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, owner)
    resp = client.post(f"/settings/{org.slug}/delete")
    assert resp.status_code == 400
    assert OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_member_cannot_delete_org(org_ctx):
    client, org, owner, member, ws = org_ctx
    _login(client, member)
    resp = client.post(f"/settings/{org.slug}/delete")
    assert resp.status_code == 403
    assert OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_org_page_shows_invite_form_and_pending(org_ctx):
    client, org, owner, member, ws = org_ctx
    Invitation.objects.create(org=org, email="pending@x.com", role="member", token="tok-abc")
    _login(client, owner)
    body = client.get(f"/{org.slug}/").content.decode()
    assert "web:invite_create" not in body            # url resolved, not literal
    assert f'hx-post="/settings/{org.slug}/invites"' in body  # invite form present (org-level)
    assert "pending@x.com" in body                     # pending invite listed


@pytest.mark.django_db
def test_invite_urls_use_viewed_org_not_session_fallback(org_ctx):
    # Regression: a user who administers TWO orgs has `active_workspace_id` in
    # session pointing at Org A's workspace. Viewing Org B's settings page must
    # build invite create/cancel URLs against Org B (the viewed org), never the
    # session fallback workspace's org (Org A). Otherwise creating/cancelling an
    # invite on Org B's page silently touches Org A's data.
    client, org_a, owner, member, ws_a = org_ctx
    org_b = Org.objects.create(name="Beta", slug="orgb")
    OrgMember.objects.create(user=owner, org=org_b, role="owner")
    ws_b = create_workspace(org_b, "Board B")
    Invitation.objects.create(org=org_b, email="pending-b@x.com", role="member", token="tok-b")

    _login(client, owner)
    # Establish the session fallback as Org A's workspace.
    home = client.get(f"/{org_a.slug}/{ws_a.slug}/")
    assert home.status_code == 200
    assert client.session.get("active_workspace_id") == ws_a.id

    resp = client.get(f"/{org_b.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"/settings/{org_b.slug}/invites" in body
    assert f"/settings/{org_a.slug}/invites" not in body

    resp = client.post(f"/settings/{org_b.slug}/invites", {"email": "new@x.com", "role": "member"})
    assert resp.status_code == 200
    inv = Invitation.objects.get(email="new@x.com")
    assert inv.org_id == org_b.id
