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
    resp = client.get("/api/check-slug", {"kind": "org", "slug": "freshname"})
    assert resp.status_code == 200
    assert resp.json() == {"available": True, "error": None}


@pytest.mark.django_db
def test_org_slug_taken(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/api/check-slug", {"kind": "org", "slug": "acme"})
    assert resp.json()["available"] is False


@pytest.mark.django_db
def test_org_slug_invalid_format(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/api/check-slug", {"kind": "org", "slug": "Bad Slug"})
    body = resp.json()
    assert body["available"] is False and body["error"]


@pytest.mark.django_db
def test_workspace_slug_scoped_to_org(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/api/check-slug",
                      {"kind": "workspace", "slug": "design", "org": "acme"})
    assert resp.json()["available"] is False  # 'design' exists in acme


@pytest.mark.django_db
def test_workspace_slug_available(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/api/check-slug",
                      {"kind": "workspace", "slug": "fresh", "org": "acme"})
    assert resp.json() == {"available": True, "error": None}


@pytest.mark.django_db
def test_unknown_kind(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/api/check-slug",
                      {"kind": "bogus", "slug": "whatever"})
    body = resp.json()
    assert body["available"] is False and body["error"]


@pytest.mark.django_db
def test_workspace_missing_org(user_ctx):
    client, org, ws = user_ctx
    resp = client.get("/api/check-slug",
                      {"kind": "workspace", "slug": "fresh"})
    body = resp.json()
    assert body["available"] is False and body["error"]


@pytest.mark.django_db
def test_workspace_kind_blocked_for_anonymous(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    create_workspace(org, "Design")
    resp = client.get("/api/check-slug",
                      {"kind": "workspace", "slug": "design", "org": "acme"})
    assert resp.json() == {"available": False, "error": "Organization not found."}


@pytest.mark.django_db
def test_workspace_kind_blocked_for_nonmember(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    create_workspace(org, "Design")
    outsider = User.objects.create(email="outsider@a.com")
    client.force_login(outsider)

    resp_taken = client.get("/api/check-slug",
                            {"kind": "workspace", "slug": "design", "org": "acme"})
    assert resp_taken.json() == {"available": False, "error": "Organization not found."}

    resp_free = client.get("/api/check-slug",
                           {"kind": "workspace", "slug": "fresh", "org": "acme"})
    assert resp_free.json() == {"available": False, "error": "Organization not found."}


@pytest.mark.django_db
@pytest.mark.parametrize("segment", ["areas", "capture", "roadmap", "orgs"])
def test_reserved_app_segment_is_unavailable(client, segment):
    resp = client.get(f"/api/check-slug?slug={segment}")
    assert resp.json() == {
        "available": False,
        "error": f"'{segment}' is reserved and can't be used.",
    }
