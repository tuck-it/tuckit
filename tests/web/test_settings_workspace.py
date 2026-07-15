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
    admin = User.objects.create(email="a@a.com")
    OrgMember.objects.create(user=admin, org=org, role="admin")
    ws1 = create_workspace(org, "One")
    ws2 = create_workspace(org, "Two")
    return client, org, admin, ws1, ws2


@pytest.mark.django_db
def test_admin_deletes_workspace(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    _login(client, admin, ws1)
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws1.slug}/delete")
    assert resp.status_code == 302
    assert not Workspace.objects.filter(id=ws1.id).exists()
    assert Workspace.objects.filter(id=ws2.id).exists()
    assert client.session.get("active_workspace_id") is None


@pytest.mark.django_db
def test_admin_deletes_workspace_htmx_redirects(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    _login(client, admin, ws1)
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws1.slug}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert resp["HX-Redirect"] == "/"  # full browser navigation, not an in-place swap
    assert not Workspace.objects.filter(id=ws1.id).exists()


@pytest.mark.django_db
def test_cannot_delete_last_workspace_via_view(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    ws2.delete()  # leave org with a single workspace (ws1)
    _login(client, admin, ws1)
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws1.slug}/delete")
    assert resp.status_code == 400
    assert Workspace.objects.filter(id=ws1.id).exists()


@pytest.mark.django_db
def test_member_cannot_delete_workspace(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    member = User.objects.create(email="m@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    _login(client, member, ws1)
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws1.slug}/delete")
    assert resp.status_code == 403
    assert Workspace.objects.filter(id=ws1.id).exists()


@pytest.mark.django_db
def test_workspace_page_renders(client_local, workspace):
    from tuckit.core.services.tokens import generate_token
    generate_token(workspace, "Existing")
    sp = f"/{workspace.org.slug}/settings/workspaces/{workspace.slug}"
    resp = client_local.get(f"{sp}/agent")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Existing" in body            # token listed
    assert "/mcp" in body                # agent snippet
    general = client_local.get(f"{sp}/general").content.decode()
    assert workspace.name in general     # rename field


@pytest.mark.django_db
def test_workspace_rename_to_duplicate_name_rejected(client_local, workspace):
    other = create_workspace(workspace.org, "Design")
    workspace.name = "Board"
    workspace.save(update_fields=["name"])
    sp = f"/{workspace.org.slug}/settings/workspaces/{workspace.slug}"
    resp = client_local.post(f"{sp}/rename", {"name": "design"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    workspace.refresh_from_db()
    assert workspace.name == "Board"


@pytest.mark.django_db
def test_workspace_rename_to_unique_name_succeeds(client_local, workspace):
    sp = f"/{workspace.org.slug}/settings/workspaces/{workspace.slug}"
    resp = client_local.post(f"{sp}/rename", {"name": "Totally Fresh Name"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    workspace.refresh_from_db()
    assert workspace.name == "Totally Fresh Name"


@pytest.mark.django_db
def test_member_cannot_rename_workspace(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    member = User.objects.create(email="m-rename@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    _login(client, member, ws1)
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws1.slug}/rename", {"name": "Renamed"})
    assert resp.status_code == 403
    ws1.refresh_from_db()
    assert ws1.name == "One"


@pytest.mark.django_db
def test_member_cannot_create_token(admin_two_ws):
    from tuckit.core.services.tokens import list_tokens
    client, org, admin, ws1, ws2 = admin_two_ws
    member = User.objects.create(email="m-tok@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    _login(client, member, ws1)
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws1.slug}/tokens", {"name": "sneaky"})
    assert resp.status_code == 403
    assert list(list_tokens(ws1)) == []


@pytest.mark.django_db
def test_member_cannot_revoke_token(admin_two_ws):
    from tuckit.core.services.tokens import generate_token, list_tokens
    client, org, admin, ws1, ws2 = admin_two_ws
    token, _raw = generate_token(ws1, "existing")
    member = User.objects.create(email="m-rev@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    _login(client, member, ws1)
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws1.slug}/tokens/{token.id}/revoke")
    assert resp.status_code == 403
    assert len(list(list_tokens(ws1))) == 1


@pytest.mark.django_db
def test_member_cannot_configure_shipped_board(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    member = User.objects.create(email="m-ship@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    _login(client, member, ws1)
    resp = client.post(
        f"/{org.slug}/settings/workspaces/{ws1.slug}/shipped-board/prefs", {"mode": "days", "limit": "30"}
    )
    assert resp.status_code == 403
    ws1.refresh_from_db()
    assert ws1.shipped_board_mode == "count"
    assert ws1.shipped_board_limit == 8


@pytest.mark.django_db
def test_admin_can_create_token(admin_two_ws):
    from tuckit.core.services.tokens import list_tokens
    client, org, admin, ws1, ws2 = admin_two_ws
    _login(client, admin, ws1)
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws1.slug}/tokens", {"name": "ci"})
    assert resp.status_code == 200
    assert len(list(list_tokens(ws1))) == 1


@pytest.mark.django_db
def test_token_and_rename_endpoints_reject_get(admin_two_ws):
    client, org, admin, ws1, ws2 = admin_two_ws
    _login(client, admin, ws1)
    assert client.get(f"/{org.slug}/settings/workspaces/{ws1.slug}/tokens").status_code == 405
    assert client.get(f"/{org.slug}/settings/workspaces/{ws1.slug}/rename").status_code == 405
