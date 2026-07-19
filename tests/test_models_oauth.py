import pytest
from django.utils import timezone
from datetime import timedelta

from tuckit.core.models import (
    Org, User, OAuthClient, OAuthAuthorizationCode,
    OAuthAccessToken, OAuthRefreshToken,
)


@pytest.mark.django_db
def test_oauth_models_persist_and_relate():
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="a@b.com", password="pw123456")
    client = OAuthClient.objects.create(
        client_id="cid123", redirect_uris=["http://localhost:9999/cb"], name="Claude Code",
    )
    code = OAuthAuthorizationCode.objects.create(
        code_hash="h" * 64, client=client, user=user, org=org,
        redirect_uri="http://localhost:9999/cb", code_challenge="chal",
        expires_at=timezone.now() + timedelta(seconds=60),
    )
    access = OAuthAccessToken.objects.create(
        token_hash="a" * 64, client=client, user=user, org=org,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    refresh = OAuthRefreshToken.objects.create(
        token_hash="r" * 64, access_token=access, client=client, user=user, org=org,
    )
    assert client.redirect_uris == ["http://localhost:9999/cb"]
    assert code.org == org
    assert access.org.oauth_tokens.first() == access
    assert refresh.revoked is False
    assert access.refresh_token == refresh
