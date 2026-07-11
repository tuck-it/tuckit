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
    assert User.objects.filter(username="local").exists()
    resp = client.get("/")
    assert resp.status_code == 302  # redirected, not a 200 app page


@pytest.mark.django_db
def test_login_grants_access(client, workspace):
    user = User.objects.get(username="local")
    user.set_password("pw123456")
    user.save()
    assert client.login(username="local", password="pw123456")
    resp = client.get("/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_healthcheck_public_when_login_required(client):
    resp = client.get("/healthcheck")
    assert resp.status_code == 200
