import types

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from starlette.testclient import TestClient

from tuckit.core.mcp.auth import require_caller
from tuckit.core.models import Org, OrgMember
from tuckit.core.services import oauth, ratelimit, throttle
from tuckit.core.services.exceptions import LimitReached
from tuckit.core.services.tokens import generate_token, hash_token


def _ctx(raw):
    request = types.SimpleNamespace(headers={"authorization": f"Bearer {raw}"})
    return types.SimpleNamespace(request_context=types.SimpleNamespace(request=request))


@pytest.fixture(autouse=True)
def clean_state():
    ratelimit.reset()
    throttle.reset()
    yield
    ratelimit.reset()
    throttle.reset()


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="a@b.co", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client = oauth.create_client("Claude Code", ["http://localhost/cb"])
    access, refresh, _ttl = oauth.issue_tokens(client, user, org, "mcp")
    return access, refresh


def test_the_memo_denies_then_expires():
    throttle.memo_block("abc", now=100.0)
    assert throttle.is_memo_blocked("abc", now=100.0)
    assert throttle.is_memo_blocked("abc", now=100.0 + throttle.BLOCK_MEMO_SECONDS - 1)
    assert not throttle.is_memo_blocked("abc", now=100.0 + throttle.BLOCK_MEMO_SECONDS)


def test_an_unknown_hash_is_not_blocked():
    assert not throttle.is_memo_blocked("never-seen")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_refusal_memoes_the_token(settings):
    settings.TUCKIT_MCP_RATE_CONN_BURST = 1.0
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 1.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 0.0
    access, _refresh = await _seed()
    await require_caller(_ctx(access))
    with pytest.raises(LimitReached):
        await require_caller(_ctx(access))
    assert throttle.is_memo_blocked(hash_token(access))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rotating_the_token_escapes_the_memo_but_not_the_bucket(settings):
    """The memo is keyed on the rotating token, so a refresh sheds it -- which is
    fine, because the authoritative bucket is keyed on the connection identity
    and is still empty. Rotation must never be a free reset."""
    settings.TUCKIT_MCP_RATE_CONN_BURST = 1.0
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 1.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 0.0
    access, refresh = await _seed()
    await require_caller(_ctx(access))
    with pytest.raises(LimitReached):
        await require_caller(_ctx(access))

    rotated = await sync_to_async(oauth.rotate_refresh_token)(refresh)
    new_access = rotated[0]
    assert not throttle.is_memo_blocked(hash_token(new_access))
    with pytest.raises(LimitReached):
        await require_caller(_ctx(new_access))


@pytest.mark.django_db(transaction=True)
def test_a_memoed_token_is_refused_by_the_transport_before_mcp_runs(asgi_app, settings):
    """The one test that exercises the real wire. Everything above talks to
    require_caller directly, which proves the decision but not that a client
    ever sees it."""
    settings.TUCKIT_MCP_RATE_CONN_BURST = 1.0
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 1.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 0.0
    org = Org.objects.create(name="Acme", slug="acme")
    _token, raw = generate_token(org, "agent")

    throttle.memo_block(hash_token(raw))
    with TestClient(asgi_app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {raw}"},
        )
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == str(throttle.BLOCK_MEMO_SECONDS)
    assert "stop and report" in resp.json()["error"], (
        "the wording has to survive all the way to the client -- it is the only "
        "thing a looping agent reads"
    )


@pytest.mark.django_db(transaction=True)
def test_an_unmemoed_token_still_reaches_mcp(asgi_app):
    """The guard must not turn into a wall for everyone else."""
    org = Org.objects.create(name="Acme", slug="acme")
    _token, raw = generate_token(org, "agent")
    with TestClient(asgi_app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {raw}"},
        )
    assert resp.status_code != 429
