import pytest

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


@pytest.fixture
def ctx(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    ws = create_workspace(org, "Product")
    client.force_login(owner)
    return client, org, owner, ws


@pytest.mark.django_db
def test_ws_general_and_agent_render(ctx):
    client, org, owner, ws = ctx
    g = client.get(f"/{org.slug}/settings/workspaces/{ws.slug}/general")
    assert g.status_code == 200 and 'class="settings-nav"' in g.content.decode()
    a = client.get(f"/{org.slug}/settings/workspaces/{ws.slug}/agent").content.decode()
    assert "/mcp" in a
    assert f'hx-post="/{org.slug}/settings/workspaces/{ws.slug}/tokens"' in a


@pytest.mark.django_db
def test_ws_rename_mutation_at_new_path(ctx):
    client, org, owner, ws = ctx
    resp = client.post(f"/{org.slug}/settings/workspaces/{ws.slug}/rename", {"name": "Renamed"})
    assert resp.status_code == 200
    ws.refresh_from_db()
    assert ws.name == "Renamed"


@pytest.mark.django_db
def test_old_workspace_settings_route_gone(ctx):
    client, org, owner, ws = ctx
    # legacy redirect alias + /workspace page removed in this task
    assert client.get(f"/settings/{org.slug}/{ws.slug}/workspace").status_code == 404
