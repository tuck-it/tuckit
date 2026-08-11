import pytest
from django.contrib.auth import get_user_model

from tuckit.core.models import OrgMember

pytestmark = pytest.mark.django_db
UM = get_user_model()


def test_get_login_shows_email_step(client):
    r = client.get("/login/")
    body = r.content.decode()
    assert r.status_code == 200
    assert 'name="email"' in body
    assert 'value="identify"' in body
    assert 'type="password"' not in body


def test_identify_existing_email_shows_password(client):
    UM.objects.create_user(email="has@x.z", password="Sup3rSecret!x")
    r = client.post("/login/", {"step": "identify", "email": "has@x.z"})
    body = r.content.decode()
    assert 'type="password"' in body
    assert 'value="login"' in body
    assert "has@x.z" in body


def test_identify_new_email_shows_set_password(client, settings):
    settings.REGISTRATION_OPEN = True
    r = client.post("/login/", {"step": "identify", "email": "new@x.z"})
    body = r.content.decode()
    assert 'type="password"' in body
    assert 'value="register"' in body


def test_login_success_redirects(client):
    UM.objects.create_user(email="ok@x.z", password="Sup3rSecret!x")
    r = client.post("/login/", {"step": "login", "email": "ok@x.z", "password": "Sup3rSecret!x"})
    assert r.status_code == 302


def test_login_wrong_password_reshows_password_step(client):
    UM.objects.create_user(email="ok@x.z", password="Sup3rSecret!x")
    r = client.post("/login/", {"step": "login", "email": "ok@x.z", "password": "nope"})
    assert r.status_code == 200
    assert "Incorrect password." in r.content.decode()


def test_register_creates_account_with_no_org_and_redirects_to_orgs(client, settings):
    settings.REGISTRATION_OPEN = True
    r = client.post("/login/", {"step": "register", "email": "fresh@x.z", "password": "Sup3rSecret!x"})
    assert r.status_code == 302
    assert r.headers["Location"] == "/orgs/"
    u = UM.objects.get(email="fresh@x.z")
    assert not OrgMember.objects.filter(user=u).exists()


def test_register_view_url_redirects_to_login(client):
    r = client.get("/register/")
    assert r.status_code in (301, 302)
    assert r.headers["Location"].rstrip("/").endswith("/login")


def test_register_redirect_keeps_the_query_string(client):
    # RedirectView drops the query string by default, which silently loses ?next=
    # (and anything else an inbound link carries) on the hop to /login/.
    r = client.get("/register/", {"next": "/acme/", "utm_source": "x"})
    assert r.status_code in (301, 302)
    location = r.headers["Location"]
    assert "next=%2Facme%2F" in location or "next=/acme/" in location
    assert "utm_source=x" in location


def test_registration_closed_unknown_email_shows_no_account(client, settings):
    settings.REGISTRATION_OPEN = False
    r = client.post("/login/", {"step": "identify", "email": "ghost@x.z"})
    assert "No account found." in r.content.decode()
