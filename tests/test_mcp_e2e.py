"""Real end-to-end MCP-over-HTTP round-trip.

Unlike tests/test_mcp_auth.py (which only asserts we don't get 401/404 and,
before the transport-security allowlist was added, actually hit a 421
Misdirected Request from the Streamable HTTP transport's Host-header
validation), this test drives the *real* MCP Streamable HTTP handshake over
Starlette's TestClient: initialize -> notifications/initialized -> tools/call.

This is the only test that exercises the real SDK accessor
`ctx.request_context.request.headers` (see core/mcp/auth.require_org)
through an actual HTTP request/response cycle rather than a hand-built fake
Context (see tests/test_mcp_tools_state.make_ctx). If an mcp SDK upgrade ever
changes that accessor's shape, this test -- not just the fake-context unit
tests -- should fail.
"""

import json

import pytest
from starlette.testclient import TestClient

from tuckit.core.models import Org, Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tokens import generate_token

_HEADERS_BASE = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest.mark.django_db(transaction=True)
def test_mcp_streamable_http_round_trip_returns_real_state(asgi_app):
    # Seed a real org/workspace/area/slice and a real hashed API token.
    org = Org.objects.create(name="Acme", slug="acme", description="demo product")
    workspace = Workspace.objects.create(org=org, name="MyProduct", slug="myproduct")
    area = create_area(workspace.org, "Backend")
    create_slice(area, "Auth", status="shipped")
    _token, raw_token = generate_token(workspace, "e2e-token")

    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {raw_token}"}

    with TestClient(asgi_app) as client:
        # 1. initialize
        init_resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "tuck-it-e2e-test", "version": "0.1"},
                },
            },
            headers=headers,
        )
        assert init_resp.status_code == 200, init_resp.text
        # The server runs the Streamable HTTP transport in STATELESS mode (see
        # core/mcp/server.py), so it issues NO Mcp-Session-Id -- each request is
        # self-contained and no follow-up needs to reference a prior session.
        # (A dedicated regression for this lives in tests/test_mcp_stateless.py.)
        assert init_resp.headers.get("mcp-session-id") is None, (
            "stateless mode must not issue an Mcp-Session-Id"
        )

        # 2. notifications/initialized (required handshake ack; no response body expected)
        notif_resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=headers,
        )
        assert notif_resp.status_code == 202, notif_resp.text

        # 3. tools/call get_project_state -- the real tool, real auth, real DB.
        call_resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_project_state", "arguments": {}},
            },
            headers=headers,
        )
        assert call_resp.status_code == 200, call_resp.text

    body = call_resp.json()
    result = body["result"]
    assert result.get("isError") is not True, result

    # mcp 1.28.1 returns dict tool results as JSON text in content[0].text,
    # not in a top-level structuredContent field.
    payload = json.loads(result["content"][0]["text"])

    assert payload["org"]["name"] == "Acme"
    assert payload["org"]["description"] == "demo product"
    [area_state] = payload["areas"]
    assert area_state["name"] == "Backend"
    assert [s["title"] for s in area_state["shipped"]] == ["Auth"]
