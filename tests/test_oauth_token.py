from urllib.parse import urlparse, parse_qs

import pytest

from tuckit.core.models import Org, User, OrgMember
from tuckit.core.services import oauth


@pytest.fixture
def granted(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="a@b.com", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    c = oauth.create_client("Claude Code", ["http://localhost:9999/cb"])
    client.force_login(user)
    verifier = "verifier-1234567890-abcdefghij"
    resp = client.post("/oauth/authorize", {
        "response_type": "code", "client_id": c.client_id,
        "redirect_uri": "http://localhost:9999/cb",
        "code_challenge": oauth.s256(verifier), "code_challenge_method": "S256",
        "state": "xyz", "scope": "mcp", "org_id": str(org.id),
    })
    code = parse_qs(urlparse(resp["Location"]).query)["code"][0]
    return org, c, code, verifier


@pytest.mark.django_db
def test_token_exchange_success(client, granted):
    org, c, code, verifier = granted
    resp = client.post("/oauth/token", {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "http://localhost:9999/cb",
        "client_id": c.client_id, "code_verifier": verifier,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == oauth.ACCESS_TTL_SECONDS
    assert oauth.resolve_oauth_org(data["access_token"]) == org
    assert data["refresh_token"]


@pytest.mark.django_db
def test_token_rejects_bad_pkce_verifier(client, granted):
    org, c, code, _verifier = granted
    resp = client.post("/oauth/token", {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "http://localhost:9999/cb",
        "client_id": c.client_id, "code_verifier": "wrong-verifier",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


@pytest.mark.django_db
def test_refresh_grant(client, granted):
    org, c, code, verifier = granted
    first = client.post("/oauth/token", {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "http://localhost:9999/cb",
        "client_id": c.client_id, "code_verifier": verifier,
    }).json()
    resp = client.post("/oauth/token", {
        "grant_type": "refresh_token", "refresh_token": first["refresh_token"],
        "client_id": c.client_id,
    })
    assert resp.status_code == 200
    assert oauth.resolve_oauth_org(resp.json()["access_token"]) == org
