import pytest
from django.test import override_settings
from django.urls import reverse


@override_settings(SOCIAL_PROVIDERS={"google": {"client_id": "id", "client_secret": "s"}})
@pytest.mark.django_db
def test_login_shows_enabled_provider_button(client):
    resp = client.get(reverse("web:login"))
    assert resp.status_code == 200
    assert b"Continue with Google" in resp.content
    assert reverse("web:social_begin", args=["google"]).encode() in resp.content
    assert b"Continue with GitHub" not in resp.content


@override_settings(SOCIAL_PROVIDERS={})
@pytest.mark.django_db
def test_login_hides_sso_block_when_none_enabled(client):
    resp = client.get(reverse("web:login"))
    assert resp.status_code == 200
    assert b"Continue with Google" not in resp.content
    assert b"auth-sso" not in resp.content  # whole block collapses
