import pytest

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


@pytest.fixture
def two_workspaces(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="o@a.com")
    user.set_password("pw123456")
    user.save()
    OrgMember.objects.create(user=user, org=org, role="owner")
    a = create_workspace(org, "Alpha")
    b = create_workspace(org, "Beta")
    return user, a, b


@pytest.mark.django_db
def test_navigating_to_workspace_sets_active(client, two_workspaces):
    # Switching is now navigation: visiting a workspace's URL makes it the active
    # workspace (TenantMiddleware records it in the session).
    user, a, b = two_workspaces
    client.force_login(user)
    resp = client.get(f"/{b.org.slug}/{b.slug}/")
    assert resp.status_code == 200
    assert client.session["active_workspace_id"] == b.id


@pytest.mark.django_db
def test_switcher_renders_sibling_workspace_links(client, two_workspaces):
    # The switcher is a popover of links, not a POST form: each accessible
    # workspace is a plain <a href="/<org>/<ws>/">.
    user, a, b = two_workspaces
    client.force_login(user)
    body = client.get(f"/{a.org.slug}/{a.slug}/").content.decode()
    assert f'href="/{b.org.slug}/{b.slug}/"' in body
    assert f'href="/{a.org.slug}/{a.slug}/"' in body


@pytest.mark.django_db
def test_old_switch_route_is_gone(client, two_workspaces):
    # The POST switch endpoints were removed when switching became link-based.
    # Trailing slash: since Task 3 the org-home catch-all (<slug:org_slug>/)
    # matches any single path segment, so a slash-less request would instead
    # trip Django's APPEND_SLASH/POST safety net rather than exercise the
    # 404-for-unknown-org path this test cares about.
    user, a, b = two_workspaces
    client.force_login(user)
    assert client.post("/switch-workspace/", {"workspace_id": b.id}).status_code == 404


@pytest.mark.django_db
def test_navigating_to_inaccessible_workspace_404s(client, two_workspaces):
    # A non-member must never reach (or learn the existence of) a foreign
    # workspace: TenantMiddleware 404s instead of the old 403.
    user, a, b = two_workspaces
    other_org = Org.objects.create(name="Other", slug="other")
    outsider_ws = create_workspace(other_org, "Foreign")
    client.force_login(user)
    resp = client.get(f"/{outsider_ws.org.slug}/{outsider_ws.slug}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_workspace_in_org(client, two_workspaces):
    user, a, b = two_workspaces
    client.force_login(user)
    resp = client.post(f"/settings/{a.org.slug}/workspaces/new", {"name": "Gamma"})
    assert resp.status_code == 302
    assert a.org.workspaces.filter(name="Gamma").exists()
    gamma = a.org.workspaces.get(name="Gamma")
    assert resp.headers["Location"] == f"/{a.org.slug}/{gamma.slug}/"
