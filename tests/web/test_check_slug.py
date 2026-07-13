import pytest

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


@pytest.fixture
def user_ctx(client, db):
    user = User.objects.create(email="u@a.com")
    org = Org.objects.create(name="Acme", slug="acme")
    OrgMember.objects.create(user=user, org=org, role="owner")
    ws = create_workspace(org, "Design")
    client.force_login(user)
    return client, org, ws


@pytest.mark.django_db
def test_org_slug_available(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/settings/check-slug", {"kind": "org", "slug": "freshname"})
    assert resp.status_code == 200
    assert resp.json() == {"available": True, "error": None}


@pytest.mark.django_db
def test_org_slug_taken(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/settings/check-slug", {"kind": "org", "slug": "acme"})
    assert resp.json()["available"] is False


@pytest.mark.django_db
def test_org_slug_invalid_format(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/settings/check-slug", {"kind": "org", "slug": "Bad Slug"})
    body = resp.json()
    assert body["available"] is False and body["error"]


@pytest.mark.django_db
def test_workspace_slug_scoped_to_org(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/settings/check-slug",
                      {"kind": "workspace", "slug": "design", "org": "acme"})
    assert resp.json()["available"] is False  # 'design' exists in acme
