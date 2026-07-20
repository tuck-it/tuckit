import base64
import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from tuckit.core.models import (
    OAuthAccessToken, OAuthAuthorizationCode, OAuthClient, OAuthRefreshToken,
)
from tuckit.core.services.tokens import hash_token

ACCESS_TTL_SECONDS = 3600


def create_client(name: str, redirect_uris: list[str]) -> OAuthClient:
    return OAuthClient.objects.create(
        client_id=secrets.token_urlsafe(24),
        redirect_uris=list(redirect_uris),
        name=name or "",
    )


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_pkce(challenge: str, verifier: str) -> bool:
    if not challenge or not verifier:
        return False
    try:
        digest = s256(verifier)
    except UnicodeEncodeError:
        return False
    return secrets.compare_digest(digest, challenge)


def create_authorization_code(
    client, user, org, redirect_uri: str, code_challenge: str, scope: str = "", ttl: int = 60
) -> str:
    raw = secrets.token_urlsafe(32)
    OAuthAuthorizationCode.objects.create(
        code_hash=hash_token(raw),
        client=client, user=user, org=org,
        redirect_uri=redirect_uri, code_challenge=code_challenge, scope=scope,
        expires_at=timezone.now() + timedelta(seconds=ttl),
    )
    return raw


def consume_authorization_code(raw: str, client, redirect_uri: str):
    """Single-use: fetch, validate client + redirect_uri + freshness, delete, return."""
    with transaction.atomic():
        rec = (
            OAuthAuthorizationCode.objects.select_for_update()
            .filter(code_hash=hash_token(raw)).first()
        )
        if rec is None:
            return None
        rec.delete()  # consume regardless of validity so a leaked code can't be retried
    if rec.client_id != client.id or rec.redirect_uri != redirect_uri:
        return None
    if rec.expires_at <= timezone.now():
        return None
    return rec


def issue_tokens(client, user, org, scope: str = "") -> tuple[str, str, int]:
    access_raw = secrets.token_urlsafe(32)
    refresh_raw = secrets.token_urlsafe(32)
    access = OAuthAccessToken.objects.create(
        token_hash=hash_token(access_raw), client=client, user=user, org=org, scope=scope,
        expires_at=timezone.now() + timedelta(seconds=ACCESS_TTL_SECONDS),
    )
    OAuthRefreshToken.objects.create(
        token_hash=hash_token(refresh_raw), access_token=access,
        client=client, user=user, org=org,
    )
    return access_raw, refresh_raw, ACCESS_TTL_SECONDS


def rotate_refresh_token(raw: str):
    with transaction.atomic():
        rt = (
            OAuthRefreshToken.objects.select_for_update()
            .select_related("client", "user", "org", "access_token")
            .filter(token_hash=hash_token(raw), revoked=False).first()
        )
        if rt is None:
            return None
        rt.revoked = True
        rt.save(update_fields=["revoked"])
        scope = rt.access_token.scope
        rt.access_token.delete()  # old access token dies with rotation
        access_raw, refresh_raw, expires_in = issue_tokens(rt.client, rt.user, rt.org, scope)
    return access_raw, refresh_raw, expires_in, scope


def resolve_oauth_org(raw: str):
    try:
        tok = OAuthAccessToken.objects.select_related("org").get(token_hash=hash_token(raw))
    except OAuthAccessToken.DoesNotExist:
        return None
    if tok.expires_at <= timezone.now():
        return None
    tok.last_used_at = timezone.now()
    tok.save(update_fields=["last_used_at"])
    return tok.org


def resolve_oauth_caller(raw: str):
    """Like resolve_oauth_org but returns (org, user) so MCP tools can know the
    acting user. Returns None if not a valid/live OAuth access token."""
    try:
        tok = OAuthAccessToken.objects.select_related("org", "user").get(token_hash=hash_token(raw))
    except OAuthAccessToken.DoesNotExist:
        return None
    if tok.expires_at <= timezone.now():
        return None
    tok.last_used_at = timezone.now()
    tok.save(update_fields=["last_used_at"])
    return tok.org, tok.user
