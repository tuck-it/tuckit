"""The MCP app has to reap its own database connections.

Django closes a request's connections from its own handler's signals. The MCP
app is mounted beside Django, never emits them, and does all its DB work on one
shared `sync_to_async(thread_sensitive=True)` thread — so without this the
connections opened there live for the life of the process.

That is invisible until something closes the socket from the far end. On
2026-08-20 production served 200s from Django while every `/mcp` call answered
"the connection is closed", permanently, because the database had been allowed
to sleep for the first time and the process kept handing out the dead handle.
It had been latent for a month behind a cron that pinged a DB-touching
healthcheck every four minutes.
"""
import json

import pytest
from starlette.testclient import TestClient

from tuckit.core.models import Org
from tuckit.core.services.tokens import generate_token

_HEADERS_BASE = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


# --------------------------------------------------------------- structure

def test_connection_reset_wraps_everything_including_the_auth_gate():
    """Outermost, or it does not help: authenticating a bearer token is itself a
    query, so it is the first thing that fails on a dead connection."""
    from tuckit.core.mcp.auth import BearerAuthMiddleware
    from tuckit.core.mcp.compose import build_mcp_app
    from tuckit.core.mcp.transport import ResetDatabaseConnections

    app = build_mcp_app()
    assert isinstance(app, ResetDatabaseConnections), (
        "the connection reset is not the outermost wrapper"
    )
    assert isinstance(app.app, BearerAuthMiddleware), (
        "something slipped between the connection reset and the auth gate"
    )


# --------------------------------------------------------------- behaviour

@pytest.fixture
def reap_calls(monkeypatch):
    """Count reaps instead of inspecting connections directly: they live on the
    executor thread, not this one, so this thread's `connections` handle is a
    different thread-local and would report nothing either way."""
    from tuckit.core.mcp import transport

    calls = []

    async def _spy():
        calls.append(1)

    monkeypatch.setattr(transport, "_close_old_connections", _spy)
    return calls


@pytest.mark.django_db(transaction=True)
def test_a_real_mcp_round_trip_reaps_before_and_after(asgi_app, reap_calls):
    org = Org.objects.create(name="Acme", slug="acme")
    _token, raw = generate_token(org, "conn-test")
    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {raw}"}

    with TestClient(asgi_app) as client:
        resp = client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        })
    assert resp.status_code == 200, resp.text
    assert len(reap_calls) >= 2, (
        f"expected a reap before and after the request, saw {len(reap_calls)}"
    )


@pytest.mark.django_db(transaction=True)
def test_an_unauthenticated_request_is_still_reaped(asgi_app, reap_calls):
    """The 401 path runs a token lookup and returns early. If the reset sat
    inside the auth gate this would be the request that leaves a dead
    connection behind for everyone after it."""
    with TestClient(asgi_app) as client:
        resp = client.post("/mcp", headers=_HEADERS_BASE, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
        })
    assert resp.status_code == 401
    assert len(reap_calls) >= 2


@pytest.mark.asyncio
async def test_a_failing_request_still_reaps_on_the_way_out():
    """`finally`, not "after a success": the request that raised is the one most
    likely to have left a broken connection behind."""
    from tuckit.core.mcp import transport

    calls = []

    async def _spy():
        calls.append(1)

    async def _boom(scope, receive, send):
        raise RuntimeError("connection went away mid-request")

    original = transport._close_old_connections
    transport._close_old_connections = _spy
    try:
        app = transport.ResetDatabaseConnections(_boom)
        with pytest.raises(RuntimeError):
            await app({"type": "http", "method": "POST", "path": "/"}, None, None)
    finally:
        transport._close_old_connections = original

    assert len(calls) == 2, "a raised request skipped the reap"


@pytest.mark.asyncio
async def test_lifespan_and_other_non_http_scopes_pass_straight_through():
    """Only HTTP requests carry queries. Reaping on a lifespan message would
    close connections out from under whatever is mid-flight."""
    from tuckit.core.mcp import transport

    calls, seen = [], []

    async def _spy():
        calls.append(1)

    async def _inner(scope, receive, send):
        seen.append(scope["type"])

    original = transport._close_old_connections
    transport._close_old_connections = _spy
    try:
        app = transport.ResetDatabaseConnections(_inner)
        await app({"type": "lifespan"}, None, None)
    finally:
        transport._close_old_connections = original

    assert seen == ["lifespan"], "the inner app was not reached"
    assert calls == [], "reaped on a non-HTTP scope"
