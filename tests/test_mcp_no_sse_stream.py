"""The server refuses the standalone SSE stream, and refuses it in the right order.

Why this exists: the SDK will happily open `GET /mcp` as a long-lived stream
that this server has nothing to push down. In production that idle stream is
what breaks -- the hosting infrastructure closes an idle connection after 240
seconds, and clients turn a dead stream into a dead transport, after which every
tool call fails with "the connection is closed" without reaching the server.
See tuckit/core/mcp/transport.RefuseSseStream.
"""

import json
import threading

import pytest
from starlette.testclient import TestClient

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.tokens import generate_token

_HEADERS_BASE = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def get_without_reading_body(client, headers, *, wait=10):
    """GET /mcp and return (status, headers, still_streaming).

    Deliberately never reads the response body. If this fix is ever removed the
    body is an SSE stream that never ends, and a plain `client.get()` would hang
    the suite rather than fail it -- a test that can only go green or go silent.
    `client.stream()` hands back the status as soon as the response starts, and
    running it in a daemon thread means a stream that stays open shows up as a
    fact we can assert on instead of a stuck process. httpx's `timeout=` does not
    help here: TestClient drives the ASGI app in-process and never trips it.
    """
    out = {}

    def run():
        try:
            with client.stream("GET", "/mcp", headers=headers) as resp:
                out["status"] = resp.status_code
                out["headers"] = dict(resp.headers)
                if resp.status_code != 200:
                    out["body"] = resp.read()
        except Exception as exc:  # noqa: BLE001
            out["exc"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=wait)
    return out, thread.is_alive()


@pytest.fixture
def org_token():
    org = Org.objects.create(name="Acme", slug="acme", description="demo")
    create_area(org, "Backend")
    _token, raw = generate_token(org, "no-sse-test")
    return org, raw


@pytest.mark.django_db(transaction=True)
def test_authenticated_get_is_refused_with_405_and_allow_post(asgi_app, org_token):
    _org, raw = org_token
    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {raw}"}

    with TestClient(asgi_app) as client:
        out, still_streaming = get_without_reading_body(client, headers)

    assert not still_streaming, "GET left a stream open -- the SSE stream is back"
    assert out.get("status") == 405, out
    # Without this header a client cannot tell "wrong method" from "wrong URL".
    assert out["headers"]["allow"] == "POST"
    assert "POST" in json.loads(out["body"])["error"]


@pytest.mark.django_db(transaction=True)
def test_unauthenticated_get_still_carries_oauth_discovery(asgi_app):
    """The 405 must not shadow the 401 that tells a client where to authenticate.

    If RefuseSseStream were wired OUTSIDE BearerAuthMiddleware this returns 405
    with no WWW-Authenticate header, and OAuth discovery over GET breaks. This
    test is the reason the ordering in tuckit/asgi.py is not arbitrary.
    """
    with TestClient(asgi_app) as client:
        out, still_streaming = get_without_reading_body(client, _HEADERS_BASE)

    assert not still_streaming, out
    assert out.get("status") == 401, out
    challenge = out["headers"]["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert "/.well-known/oauth-protected-resource/mcp" in challenge


@pytest.mark.django_db(transaction=True)
def test_post_round_trip_still_works_after_the_stream_is_refused(asgi_app, org_token):
    """Refusing the stream must cost nothing on the path that actually carries work."""
    _org, raw = org_token
    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {raw}"}

    with TestClient(asgi_app) as client:
        out, _ = get_without_reading_body(client, headers)
        assert out.get("status") == 405, out

        init = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "no-sse-test", "version": "0.1"},
                },
            },
            headers=headers,
        )
        assert init.status_code == 200, init.text

        called = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_areas", "arguments": {}},
            },
            headers=headers,
        )

    assert called.status_code == 200, called.text
    payload = called.json()
    assert "error" not in payload, payload
    # Assert the real area came back, not merely that the call was accepted.
    body = json.dumps(payload)
    assert "Backend" in body, body
