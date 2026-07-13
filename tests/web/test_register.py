import pytest
from django.test import override_settings

from tuckit.core.models import Org, User


@pytest.mark.django_db
@override_settings(REGISTRATION_OPEN=False)
def test_register_closed_returns_404(client):
    assert client.get("/register/").status_code == 404


@pytest.mark.django_db
@override_settings(REGISTRATION_OPEN=True)
def test_register_open_creates_account_and_logs_in(client):
    resp = client.post("/register/", {
        "email": "new@x.com", "org_name": "NewCo", "slug": "newco", "password": "pw123456",
    })
    assert resp.status_code == 302
    assert User.objects.filter(email="new@x.com").exists()
    assert Org.objects.filter(slug="newco").exists()
    # logged in: home is now reachable
    assert client.get("/").status_code == 200


@pytest.mark.django_db
@override_settings(REGISTRATION_OPEN=True)
def test_register_duplicate_slug_shows_error(client):
    Org.objects.create(name="Taken", slug="taken")
    resp = client.post("/register/", {
        "email": "new@x.com", "org_name": "X", "slug": "taken", "password": "pw123456",
    })
    assert resp.status_code == 200  # re-rendered with error
    assert not User.objects.filter(email="new@x.com").exists()


@pytest.mark.django_db
def test_register_rejects_bad_slug(client, settings):
    settings.REGISTRATION_OPEN = True
    resp = client.post("/register/", {
        "email": "z@a.com", "org_name": "Acme", "slug": "Bad Slug!",
        "password": "sufficiently-long-pw-123",
    })
    assert resp.status_code == 200  # form re-rendered
    assert not User.objects.filter(email="z@a.com").exists()
    assert not Org.objects.filter(name="Acme").exists()


@pytest.mark.django_db
def test_register_accepts_valid_slug(client, settings):
    settings.REGISTRATION_OPEN = True
    resp = client.post("/register/", {
        "email": "z2@a.com", "org_name": "Acme", "slug": "acme",
        "password": "sufficiently-long-pw-123",
    })
    assert resp.status_code == 302
    assert Org.objects.get(slug="acme")


@pytest.mark.django_db
def test_check_slug_reachable_anonymously(client):
    """/settings/check-slug must be login_not_required so the anonymous
    registration page's live-availability JS can call it."""
    resp = client.get("/settings/check-slug", {"kind": "org", "slug": "anon-check"})
    assert resp.status_code == 200
