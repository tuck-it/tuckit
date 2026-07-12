import pytest

from tuckit.core.models import Org, OrgMember, User, Workspace
from tuckit.core.services.orgs import create_workspace


def _login(client, user, ws):
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()


@pytest.fixture
def admin_two_ws(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    admin = User.objects.create(username="a@a.com", email="a@a.com")
    OrgMember.objects.create(user=admin, org=org, role="admin")
    ws1 = create_workspace(org, "One")
    ws2 = create_workspace(org, "Two")
    return client, org, admin, ws1, ws2


@pytest.mark.django_db
def test_admin_deletes_workspace(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    _login(client, admin, ws1)
    resp = client.post("/settings/workspace/delete")
    assert resp.status_code == 302
    assert not Workspace.objects.filter(id=ws1.id).exists()
    assert Workspace.objects.filter(id=ws2.id).exists()
    assert client.session.get("active_workspace_id") is None


@pytest.mark.django_db
def test_admin_deletes_workspace_htmx_redirects(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    _login(client, admin, ws1)
    resp = client.post("/settings/workspace/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert resp["HX-Redirect"] == "/"  # full browser navigation, not an in-place swap
    assert not Workspace.objects.filter(id=ws1.id).exists()


@pytest.mark.django_db
def test_cannot_delete_last_workspace_via_view(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    ws2.delete()  # leave org with a single workspace (ws1)
    _login(client, admin, ws1)
    resp = client.post("/settings/workspace/delete")
    assert resp.status_code == 400
    assert Workspace.objects.filter(id=ws1.id).exists()


@pytest.mark.django_db
def test_member_cannot_delete_workspace(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    member = User.objects.create(username="m@a.com", email="m@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    _login(client, member, ws1)
    resp = client.post("/settings/workspace/delete")
    assert resp.status_code == 403
    assert Workspace.objects.filter(id=ws1.id).exists()


@pytest.mark.django_db
def test_workspace_page_renders(client_local, workspace):
    from tuckit.core.services.tokens import generate_token
    generate_token(workspace, "Existing")
    resp = client_local.get("/settings/workspace")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert workspace.name in body        # rename field
    assert "Existing" in body            # token listed
    assert "/mcp" in body                # agent snippet
    assert "/settings/org" in body       # member-management link to org page


@pytest.mark.django_db
def test_old_settings_redirects_to_workspace(client_local, workspace):
    resp = client_local.get("/settings/")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/settings/workspace"
