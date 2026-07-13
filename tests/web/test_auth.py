import pytest

from tuckit.core.models import User


@pytest.mark.django_db
def test_anonymous_redirected_to_login(client, workspace):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


@pytest.mark.django_db
def test_local_user_not_auto_logged_in(client, workspace):
    # The bootstrapped "local" user exists, but an anonymous request must
    # NOT be silently authenticated as it (regression on LocalUserMiddleware).
    assert User.objects.filter(email="local@tuckit.local").exists()
    resp = client.get("/")
    assert resp.status_code == 302  # redirected, not a 200 app page


@pytest.mark.django_db
def test_login_grants_access(client, workspace):
    user = User.objects.get(email="local@tuckit.local")
    user.set_password("pw123456")
    user.save()
    assert client.login(username="local@tuckit.local", password="pw123456")
    resp = client.get("/", follow=True)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_healthcheck_public_when_login_required(client):
    resp = client.get("/healthcheck")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_login_form_authenticates_by_email(client):
    # Regression: the login form field is named "username" (Django's
    # AuthenticationForm) but authenticates by USERNAME_FIELD=email — posting
    # the email logs you in through the real HTTP form path.
    from tuckit.core.services.accounts import register

    register(email="e2e@x.com", org_name="E2E", slug="e2e", password="pw12345678")

    ok = client.post("/login/", {"username": "e2e@x.com", "password": "pw12345678"})
    assert ok.status_code == 302
    assert client.get("/", follow=True).status_code == 200

    client.logout()
    bad = client.post("/login/", {"username": "e2e@x.com", "password": "nope"})
    assert bad.status_code == 200  # form re-renders, not authenticated
