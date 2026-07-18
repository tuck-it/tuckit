import pytest
from django.test import override_settings

from tuckit.core.models import Area, Org, User

pytestmark = pytest.mark.django_db


def _signup(client, email="new@x.com", password="pw12345678"):
    """Email-first sign-up: creating the account (org comes later at /orgs)."""
    return client.post("/login/", {"step": "register", "email": email, "password": password})


@override_settings(REGISTRATION_OPEN=True)
def test_signup_creates_account_with_no_org_and_logs_in(client):
    r = _signup(client)
    assert r.status_code == 302
    u = User.objects.get(email="new@x.com")
    assert not Org.objects.filter(members__user=u).exists()  # account only, no org yet
    assert client.get("/orgs/").status_code == 200  # logged in -> org picker reachable


@override_settings(REGISTRATION_OPEN=False)
def test_signup_closed_shows_no_account(client):
    r = client.post("/login/", {"step": "identify", "email": "ghost@x.com"})
    assert r.status_code == 200
    assert "No account found." in r.content.decode()
    assert not User.objects.filter(email="ghost@x.com").exists()


@override_settings(REGISTRATION_OPEN=True)
def test_signup_then_create_org_lands_home(client):
    _signup(client, email="e2e@x.com")
    r = client.post("/orgs/", {"name": "Acme", "slug": "acme"})
    assert r.status_code == 302
    assert r.headers["Location"] == "/acme/"
    u = User.objects.get(email="e2e@x.com")
    org = Org.objects.get(members__user=u)
    assert org.slug == "acme"
    assert Area.objects.filter(org=org, is_triage=True).count() == 1


@override_settings(REGISTRATION_OPEN=True)
def test_create_org_rejects_bad_slug(client):
    _signup(client, email="z@a.com")
    r = client.post("/orgs/", {"name": "Acme", "slug": "Bad Slug!"})
    assert r.status_code == 200
    assert not Org.objects.filter(name="Acme").exists()


@override_settings(REGISTRATION_OPEN=True)
def test_create_org_rejects_duplicate_slug(client):
    Org.objects.create(name="Taken", slug="taken")
    _signup(client, email="d@a.com")
    r = client.post("/orgs/", {"name": "X", "slug": "taken"})
    assert r.status_code == 200
    assert "already taken" in r.content.decode().lower()


def test_check_slug_reachable_anonymously(client):
    """/api/check-slug must be login_not_required so the org-create page's
    live-availability JS can call it."""
    resp = client.get("/api/check-slug", {"kind": "org", "slug": "anon-check"})
    assert resp.status_code == 200
