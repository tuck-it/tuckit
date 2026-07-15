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
def test_org_general_renders_in_settings_shell(ctx):
    client, org, owner, ws = ctx
    resp = client.get(f"/{org.slug}/settings/general")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'class="settings-nav"' in body          # swapped sidebar, not product sidebar
    assert 'class="sidebar"' not in body           # product sidebar absent
    assert f'href="/{org.slug}/{ws.slug}/"' in body  # Back to app → current workspace
    assert "Acme" in body
    assert 'class="crumbbar"' not in body          # app breadcrumb suppressed in settings shell


@pytest.mark.django_db
def test_settings_root_redirects_to_workspace_general(ctx):
    client, org, owner, ws = ctx
    resp = client.get(f"/{org.slug}/settings/")
    assert resp.status_code in (301, 302)
    assert resp["Location"] == f"/{org.slug}/settings/workspaces/{ws.slug}/general"


@pytest.mark.django_db
def test_settings_general_404_for_nonmember(ctx):
    client, org, owner, ws = ctx
    other = Org.objects.create(name="Other", slug="other")
    stranger = User.objects.create(email="s@s.com")
    OrgMember.objects.create(user=stranger, org=other, role="owner")
    client.force_login(stranger)
    assert client.get(f"/{org.slug}/settings/general").status_code == 404
