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


def test_is_memo_blocked_does_not_evict_expired_entries():
    """is_memo_blocked runs on the event loop; memo_block's sweep runs on the
    executor thread. If the read path also deleted, the two could race on the
    same dict from two different threads (KeyError on a double-delete,
    RuntimeError iterating _blocked_until while it mutates). Eviction has to
    live solely on the write path (memo_block's sweep) for the no-lock design
    to be safe, so a read of an expired entry must leave the dict untouched."""
    throttle.memo_block("abc", now=100.0)
    assert not throttle.is_memo_blocked("abc", now=100.0 + throttle.BLOCK_MEMO_SECONDS)
    assert "abc" in throttle._blocked_until


def test_memo_block_sweeps_expired_entries_on_insert():
    """A rotated access token never presents its old hash again, so
    expiry-on-read alone would leak that entry forever. Assert directly on
    the dict, not on is_memo_blocked: expiry-on-read already makes
    is_memo_blocked return False for an expired entry whether or not the
    entry was actually freed, so that alone would prove nothing about the
    leak this guards against.
    """
    throttle.memo_block("hash-1", now=0.0)
    throttle.memo_block("hash-2", now=0.0)
    throttle.memo_block("hash-3", now=0.0)
    assert len(throttle._blocked_until) == 3

    throttle.memo_block("hash-4", now=throttle.BLOCK_MEMO_SECONDS + 1)

    assert set(throttle._blocked_until) == {"hash-4"}


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
