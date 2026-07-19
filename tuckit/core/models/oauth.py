from django.db import models

from tuckit.core.models.accounts import User
from tuckit.core.models.org import Org


class OAuthClient(models.Model):
    """An OAuth client, created by Dynamic Client Registration (RFC 7591).
    Public clients (Claude Code, Cursor) carry no secret."""
    client_id = models.CharField(max_length=64, unique=True)
    client_secret_hash = models.CharField(max_length=64, blank=True, default="")
    redirect_uris = models.JSONField(default=list)
    name = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name or self.client_id}"


class OAuthAuthorizationCode(models.Model):
    """Single-use, short-lived authorization code binding a grant to
    user + org + client + PKCE challenge."""
    code_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    org = models.ForeignKey(Org, on_delete=models.CASCADE)
    redirect_uri = models.CharField(max_length=2000)
    code_challenge = models.CharField(max_length=128)
    scope = models.CharField(max_length=500, blank=True, default="")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class OAuthAccessToken(models.Model):
    """Opaque, org-scoped access token. Only the SHA-256 hash is stored."""
    token_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="oauth_tokens")
    scope = models.CharField(max_length=500, blank=True, default="")
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class OAuthRefreshToken(models.Model):
    """Long-lived, rotated-on-use refresh token, 1:1 with an access token."""
    token_hash = models.CharField(max_length=64, unique=True)
    access_token = models.OneToOneField(
        OAuthAccessToken, on_delete=models.CASCADE, related_name="refresh_token"
    )
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    org = models.ForeignKey(Org, on_delete=models.CASCADE)
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
