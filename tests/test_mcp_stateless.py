"""Regression: the MCP Streamable HTTP transport must run in STATELESS mode.

Root cause of the production "connects then disconnects" symptom: FastMCP's
default *stateful* mode keeps per-session state in the serving process's local
memory and issues an ``Mcp-Session-Id`` that every follow-up request must carry
back to *that same* process. On Cloud Run (scale-to-zero, up to 4 instances,
``sessionAffinity=false``) a follow-up request routinely lands on a *different*
instance -- or the instance holding the session is reaped when the service
scales to zero on idle -- so the session is gone and the request 404s, which the
client surfaces as a dropped connection. (Confirmed in Cloud Run logs:
intermittent ``404`` GET/POST ``/mcp``, plus every server->client SSE GET stream
terminated at the 300s request timeout.)

Stateless mode removes the per-process session entirely: each request is
self-contained, so any instance can serve it and scale-to-zero cannot lose it.
This server exposes only plain request/response tools (no server-initiated
notifications, sampling, or subscriptions), so stateless mode costs nothing.

Both tests below fail in stateful mode and pass in stateless mode.
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

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "tuck-it-stateless-test", "version": "0.1"},
    },
}


def _seed_token():
    org = Org.objects.create(name="Acme", slug="acme")
    workspace = Workspace.objects.create(
        org=org, name="MyProduct", slug="myproduct", description="demo product"
    )
    create_slice(create_area(workspace.org, "Backend"), "Auth", status="shipped")
    _token, raw_token = generate_token(workspace, "stateless-token")
    return raw_token


@pytest.mark.django_db(transaction=True)
def test_initialize_issues_no_session_id(asgi_app):
    """Stateless mode must NOT issue an Mcp-Session-Id.

    A session id is the tell-tale of stateful mode: it binds the client to the
    one process that holds the session in memory. Stateless mode issues none.
    """
    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {_seed_token()}"}
    with TestClient(asgi_app) as client:
        init_resp = client.post("/mcp", json=_INITIALIZE, headers=headers)
        assert init_resp.status_code == 200, init_resp.text
        assert init_resp.headers.get("mcp-session-id") is None, (
            "stateless mode must not issue an Mcp-Session-Id "
            f"(got {init_resp.headers.get('mcp-session-id')!r})"
        )


@pytest.mark.django_db(transaction=True)
def test_tool_call_without_session_id_succeeds(asgi_app):
    """A tools/call carrying NO session id must succeed with real data.

    This is the production failure reproduced in-process: a request that does
    not (cannot) reference a session living in some *other* instance's memory.
    In stateful mode the transport rejects it (missing/unknown session); in
    stateless mode every instance can serve it, which is the fix.
    """
    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {_seed_token()}"}
    with TestClient(asgi_app) as client:
        # Real clients still open with initialize; stateless just doesn't bind us
        # to the responding instance afterwards.
        init_resp = client.post("/mcp", json=_INITIALIZE, headers=headers)
        assert init_resp.status_code == 200, init_resp.text

        # Follow-up tools/call WITHOUT any Mcp-Session-Id -- the "landed on a
        # different / freshly-started instance" scenario.
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

    result = call_resp.json()["result"]
    assert result.get("isError") is not True, result
    payload = json.loads(result["content"][0]["text"])
    assert payload["org"]["name"] == "Acme"
