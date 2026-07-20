import pytest
from django.test import override_settings
from django.urls import reverse

from tuckit.core.models import User
from tuckit.core.services.social.providers import SocialIdentity

GOOGLE = {"google": {"client_id": "id", "client_secret": "sec"}}


@override_settings(SOCIAL_PROVIDERS=GOOGLE)
@pytest.mark.django_db
def test_begin_redirects_and_sets_session_state(client):
    resp = client.get(reverse("web:social_begin", args=["google"]))
    assert resp.status_code == 302
    assert resp["Location"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert client.session["social_oauth"]["provider"] == "google"
    assert client.session["social_oauth"]["state"]


@override_settings(SOCIAL_PROVIDERS={})
@pytest.mark.django_db
def test_begin_404_when_provider_disabled(client):
    resp = client.get(reverse("web:social_begin", args=["google"]))
    assert resp.status_code == 404


@override_settings(SOCIAL_PROVIDERS=GOOGLE)
@pytest.mark.django_db
def test_callback_logs_in_existing_linked_user(client, monkeypatch):
    from tuckit.core.models import SocialAccount
    u = User.objects.create_user(email="u@g.com", password="pw123456")
    SocialAccount.objects.create(user=u, provider="google", uid="sub-1")

    monkeypatch.setattr(
        "tuckit.web.views.social.exchange_and_fetch",
        lambda *a, **k: SocialIdentity("sub-1", "u@g.com", True, "U"),
    )
    # Prime session state as begin() would have:
    s = client.session
    s["social_oauth"] = {"provider": "google", "state": "st", "code_verifier": "cv", "next": ""}
    s.save()

    resp = client.get(reverse("web:social_callback", args=["google"]) + "?state=st&code=abc")
    assert resp.status_code == 302
    assert client.session["_auth_user_id"] == str(u.pk)


@override_settings(SOCIAL_PROVIDERS=GOOGLE)
@pytest.mark.django_db
def test_callback_rejects_state_mismatch(client, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        "tuckit.web.views.social.exchange_and_fetch",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    s = client.session
    s["social_oauth"] = {"provider": "google", "state": "expected", "code_verifier": "cv", "next": ""}
    s.save()

    resp = client.get(reverse("web:social_callback", args=["google"]) + "?state=WRONG&code=abc")
    assert resp.status_code == 200  # re-rendered login, not logged in
    assert "_auth_user_id" not in client.session
    assert called["n"] == 0  # never reached token exchange


@override_settings(SOCIAL_PROVIDERS=GOOGLE, REGISTRATION_OPEN=False)
@pytest.mark.django_db
def test_callback_shows_error_when_registration_closed(client, monkeypatch):
    monkeypatch.setattr(
        "tuckit.web.views.social.exchange_and_fetch",
        lambda *a, **k: SocialIdentity("sub-new", "new@g.com", True, "New"),
    )
    s = client.session
    s["social_oauth"] = {"provider": "google", "state": "st", "code_verifier": "cv", "next": ""}
    s.save()

    resp = client.get(reverse("web:social_callback", args=["google"]) + "?state=st&code=abc")
    assert resp.status_code == 200
    assert b"No account found." in resp.content


@override_settings(SOCIAL_PROVIDERS=GOOGLE)
@pytest.mark.django_db
def test_callback_with_provider_error_param_shows_generic_error(client, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        "tuckit.web.views.social.exchange_and_fetch",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    s = client.session
    s["social_oauth"] = {"provider": "google", "state": "st", "code_verifier": "cv", "next": ""}
    s.save()

    resp = client.get(
        reverse("web:social_callback", args=["google"]) + "?error=access_denied&state=st"
    )
    assert resp.status_code == 200
    assert "_auth_user_id" not in client.session
    assert called["n"] == 0  # token exchange never reached on the error path
    assert b"access_denied" not in resp.content  # raw provider error never echoed


@override_settings(SOCIAL_PROVIDERS=GOOGLE)
@pytest.mark.django_db
def test_callback_exchange_failure_shows_generic_error(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom-secret-detail")

    monkeypatch.setattr("tuckit.web.views.social.exchange_and_fetch", boom)
    s = client.session
    s["social_oauth"] = {"provider": "google", "state": "st", "code_verifier": "cv", "next": ""}
    s.save()

    resp = client.get(reverse("web:social_callback", args=["google"]) + "?state=st&code=abc")
    assert resp.status_code == 200
    assert "_auth_user_id" not in client.session
    assert b"boom-secret-detail" not in resp.content  # exception detail never echoed
