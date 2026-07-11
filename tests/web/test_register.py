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
