"""OAuth 2.1 end-to-end + regression tests: org-scoping isolation, stateless
survival across a fresh ASGI/MCP instance, revocation, and a real MCP wire
tool call authenticated with an OAuth access token (proving OAuth->Org
resolution actually flows through require_org on a live tool, not just
JSON-RPC `ping`)."""

import json
from urllib.parse import urlparse, parse_qs

import pytest
from starlette.testclient import TestClient

from tuckit.core.models import Org, User, OrgMember, Area
from tuckit.core.services import oauth
from tuckit.core.services.areas import create_area


def _grant_access(client, org, user, c):
    client.force_login(user)
    verifier = "verifier-1234567890-abcdefghij"
    r = client.post("/oauth/authorize", {
        "response_type": "code", "client_id": c.client_id,
        "redirect_uri": "http://localhost:9999/cb",
        "code_challenge": oauth.s256(verifier), "code_challenge_method": "S256",
        "scope": "mcp", "org_id": str(org.id),
    })
    code = parse_qs(urlparse(r["Location"]).query)["code"][0]
    tok = client.post("/oauth/token", {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "http://localhost:9999/cb",
        "client_id": c.client_id, "code_verifier": verifier,
    }).json()
    return tok["access_token"]


@pytest.mark.django_db
def test_oauth_token_is_org_scoped(client):
    org_a = Org.objects.create(name="A", slug="a")
    org_b = Org.objects.create(name="B", slug="b")
    user = User.objects.create_user(email="a@b.com", password="pw123456")
    OrgMember.objects.create(user=user, org=org_a, role="owner")
    OrgMember.objects.create(user=user, org=org_b, role="owner")
    c = oauth.create_client("Claude Code", ["http://localhost:9999/cb"])
    access = _grant_access(client, org_a, user, c)
    # The token resolves to org A only.
    assert oauth.resolve_oauth_org(access) == org_a
    assert oauth.resolve_oauth_org(access) != org_b


@pytest.mark.django_db(transaction=True)
def test_stateless_flow_survives_fresh_asgi_instance(asgi_app, client):
    """Authorize+token happen on the Django side; a FRESH ASGI/MCP instance
    (asgi_app fixture reloads the MCP package) still accepts the token, proving
    no in-memory OAuth state."""
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="a@b.com", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    c = oauth.create_client("Claude Code", ["http://localhost:9999/cb"])
    access = _grant_access(client, org, user, c)
    with TestClient(asgi_app) as wire:
        resp = wire.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code not in (401, 404)


@pytest.mark.django_db
def test_disconnect_then_token_is_dead(client):
    from tuckit.core.services.oauth_apps import disconnect_app
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="a@b.com", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    c = oauth.create_client("Claude Code", ["http://localhost:9999/cb"])
    access = _grant_access(client, org, user, c)
    disconnect_app(org, c.client_id)
    assert oauth.resolve_oauth_org(access) is None


# --- Addition A (MED-1): an OAuth access token authorizes a REAL MCP tool call ---

_HEADERS_BASE = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest.mark.django_db(transaction=True)
def test_oauth_token_authorizes_real_tool_call_scoped_to_its_org(asgi_app):
    """Mirrors tests/test_mcp_e2e.py's real initialize -> notifications/initialized
    -> tools/call handshake over Starlette's TestClient, but authenticates with an
    OAuth access token (oauth.issue_tokens) instead of a legacy ApiToken. Proves the
    token resolves to a specific Org through a real tool invocation (require_org),
    not merely that JSON-RPC `ping` doesn't 401/404 (see test_mcp_oauth_auth.py)."""
    org_a = Org.objects.create(name="Acme", slug="acme")
    org_b = Org.objects.create(name="Other", slug="other")
    user = User.objects.create_user(email="a@b.com", password="pw123456")
    c = oauth.create_client("Claude Code", ["http://localhost:9999/cb"])
    access, _refresh, _expires_in = oauth.issue_tokens(c, user, org_a, "mcp")

    # Seed a decoy area in a DIFFERENT org -- if the token resolved to the wrong
    # org (or to no org at all / global data), this would leak through.
    create_area(org_b, "OrgB-Secret")

    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {access}"}

    with TestClient(asgi_app) as wire:
        init_resp = wire.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "tuck-it-oauth-e2e-test", "version": "0.1"},
                },
            },
            headers=headers,
        )
        assert init_resp.status_code == 200, init_resp.text

        notif_resp = wire.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=headers,
        )
        assert notif_resp.status_code == 202, notif_resp.text

        # Create an area via the real tool -- proves writes land in the
        # token's org (org_a), not some other org.
        create_resp = wire.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "create_area", "arguments": {"name": "OrgA-Area"}},
            },
            headers=headers,
        )
        assert create_resp.status_code == 200, create_resp.text
        create_result = create_resp.json()["result"]
        assert create_result.get("isError") is not True, create_result
        created = json.loads(create_result["content"][0]["text"])
        assert created["name"] == "OrgA-Area"

        # List areas via the real tool -- must see only org_a's data.
        list_resp = wire.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_areas", "arguments": {}},
            },
            headers=headers,
        )
        assert list_resp.status_code == 200, list_resp.text
        list_result = list_resp.json()["result"]
        assert list_result.get("isError") is not True, list_result
        # list_areas returns list[dict]; FastMCP puts the structured form (a real
        # JSON array) in structuredContent.result, while content[0].text is the
        # ad hoc *unstructured* rendering (one text block per list item -- see
        # mcp.server.fastmcp.utilities.func_metadata._convert_to_content), which
        # for a single-item list is indistinguishable from a dict result. Use
        # structuredContent here, matching how a real MCP client would consume a
        # list-returning tool.
        areas = list_result["structuredContent"]["result"]

    names = [a["name"] for a in areas]
    assert "OrgA-Area" in names
    assert "OrgB-Secret" not in names

    # And directly in the DB: the area the tool created really belongs to org_a.
    assert Area.objects.get(name="OrgA-Area").org_id == org_a.id


@pytest.mark.django_db(transaction=True)
def test_brand_new_account_authorizes_by_creating_its_first_workspace(asgi_app, client):
    """The plugin-install path: sign up, land on consent with no workspace,
    create one there, and come out holding a token that works on the wire.

    Regression for the dead end where an account with no org rendered an empty
    required <select> and could not press Allow at all."""
    user = User.objects.create_user(email="brand@new.com", password="pw123456")
    assert not Org.objects.filter(members__user=user).exists()
    c = oauth.create_client("Claude Code", ["http://localhost:9999/cb"])

    client.force_login(user)
    verifier = "verifier-1234567890-abcdefghij"
    r = client.post("/oauth/authorize", {
        "response_type": "code", "client_id": c.client_id,
        "redirect_uri": "http://localhost:9999/cb",
        "code_challenge": oauth.s256(verifier), "code_challenge_method": "S256",
        "scope": "mcp", "org_id": "__new__", "org_name": "Brand New",
    })
    assert r.status_code == 302, "a user with no workspace must still be able to Allow"
    code = parse_qs(urlparse(r["Location"]).query)["code"][0]

    tok = client.post("/oauth/token", {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "http://localhost:9999/cb",
        "client_id": c.client_id, "code_verifier": verifier,
    }).json()
    access = tok["access_token"]

    org = Org.objects.get(name="Brand New")
    assert OrgMember.objects.filter(user=user, org=org, role="owner").exists()
    assert oauth.resolve_oauth_org(access) == org

    # And the token actually works on the MCP wire, not just in the DB.
    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {access}"}
    with TestClient(asgi_app) as wire:
        init_resp = wire.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "tuck-it-first-workspace-test", "version": "0.1"},
                },
            },
            headers=headers,
        )
        assert init_resp.status_code == 200, init_resp.text

        notif_resp = wire.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=headers,
        )
        assert notif_resp.status_code == 202, notif_resp.text

        list_resp = wire.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "list_areas", "arguments": {}},
            },
            headers=headers,
        )
        assert list_resp.status_code == 200, list_resp.text
        result = list_resp.json()["result"]
        assert result.get("isError") is not True, result
