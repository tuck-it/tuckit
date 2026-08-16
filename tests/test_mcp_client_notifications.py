"""Regression: a client notification must never come back as an error status.

From protocol 2026-07-28 the SDK routes any request whose
``MCP-Protocol-Version`` it does not recognise as a handshake version to its
"modern" transport, which answers 400 to any body that is not a single
JSON-RPC request object. A notification is exactly that, so a client that
POSTs one gets an error for a message it never asked to be answered -- and
reads it as the transport dying, not as one message being refused:

    MCP server connection closed unexpectedly for tuckit:
    sending "notifications/roots/list_changed": Bad Request

Observed against Antigravity CLI 1.1.13, whose first probe already tags
requests ``2026-07-28`` and which declares ``roots.listChanged``. The tools
appear, then quietly stop existing mid-session.

The version matrix below is the point of the file: the pre-2026 versions pass
without the fix, so a test that only used the negotiated version would stay
green while production stayed broken.
"""

import json

import pytest
from starlette.testclient import TestClient

from tuckit.core.mcp.transport import _is_notification
from tuckit.core.models import Org
from tuckit.core.services.tokens import generate_token

_HEADERS_BASE = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

_ROOTS_CHANGED = {"jsonrpc": "2.0", "method": "notifications/roots/list_changed"}

# The four the SDK knows as handshake versions, the modern one Antigravity
# probes with, and one it cannot know -- everything outside the handshake set
# takes the modern path, so an unknown value must behave like 2026-07-28.
PROTOCOL_VERSIONS = [
    None,
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    "2026-07-28",
    "2099-01-01",
]


def _auth_headers():
    org = Org.objects.create(name="Acme", slug="acme", description="demo product")
    _token, raw_token = generate_token(org, "notification-token")
    return {**_HEADERS_BASE, "Authorization": f"Bearer {raw_token}"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("version", PROTOCOL_VERSIONS)
def test_client_notification_is_accepted_at_every_protocol_version(asgi_app, version):
    headers = _auth_headers()
    if version is not None:
        headers["MCP-Protocol-Version"] = version

    with TestClient(asgi_app) as client:
        resp = client.post("/mcp", json=_ROOTS_CHANGED, headers=headers)

    assert resp.status_code == 202, (
        f"protocol {version}: a notification must be accepted, not answered "
        f"with {resp.status_code} {resp.text!r}"
    )
    assert resp.content == b"", "202 carries no body; there is nothing to reply"


@pytest.mark.django_db(transaction=True)
def test_a_batch_of_only_notifications_is_accepted(asgi_app):
    """Clients that pack notifications together must not fare worse than one
    that sends them singly."""
    headers = {**_auth_headers(), "MCP-Protocol-Version": "2026-07-28"}
    batch = [{"jsonrpc": "2.0", "method": "notifications/initialized"}, _ROOTS_CHANGED]

    with TestClient(asgi_app) as client:
        resp = client.post("/mcp", json=batch, headers=headers)

    assert resp.status_code == 202, resp.text


@pytest.mark.django_db(transaction=True)
def test_a_request_still_reaches_the_sdk(asgi_app):
    """The guard keys on the absence of `id`, so anything expecting an answer
    must pass through untouched -- otherwise it would swallow real calls."""
    headers = _auth_headers()

    with TestClient(asgi_app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}},
            headers=headers,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == 7
    assert any(t["name"] == "get_project_state" for t in body["result"]["tools"])


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"jsonrpc": "2.0", "method": "notifications/initialized"}, True),
        ({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, False),
        # `"id": null` is a malformed request rather than a notification, and
        # the difference has to be read off the key, not its value. Today the
        # SDK answers both 202 so HTTP cannot tell them apart -- which is
        # exactly why the distinction is pinned here instead of over a request.
        ({"jsonrpc": "2.0", "id": None, "method": "tools/list"}, False),
        ([{"jsonrpc": "2.0", "method": "notifications/initialized"}], True),
        # A batch carrying a request must reach the SDK, which is the only
        # thing that can answer the request half of it.
        ([{"jsonrpc": "2.0", "method": "x"}, {"jsonrpc": "2.0", "id": 1, "method": "y"}], False),
        ([], False),
        ("not an object", False),
    ],
)
def test_only_a_body_with_no_id_counts_as_a_notification(body, expected):
    assert _is_notification(body) is expected


@pytest.mark.django_db(transaction=True)
def test_an_unauthenticated_notification_still_gets_the_oauth_challenge(asgi_app):
    """The guard sits inside the auth gate. A 202 here would tell an
    unauthenticated client all was well and strip the discovery header that
    starts OAuth."""
    with TestClient(asgi_app) as client:
        resp = client.post("/mcp", json=_ROOTS_CHANGED, headers=_HEADERS_BASE)

    assert resp.status_code == 401, resp.text
    assert "resource_metadata=" in resp.headers.get("www-authenticate", "")


@pytest.mark.django_db(transaction=True)
def test_malformed_json_is_left_to_the_sdk(asgi_app):
    """The guard must not invent a parse-error shape of its own."""
    headers = _auth_headers()

    with TestClient(asgi_app) as client:
        resp = client.post("/mcp", content=b"{not json", headers=headers)

    assert resp.status_code != 202
    assert json.loads(resp.content)["error"]["message"]
