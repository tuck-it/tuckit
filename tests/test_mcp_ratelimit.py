import types

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from tuckit.core.mcp.auth import require_caller
from tuckit.core.models import Org, OrgMember
from tuckit.core.services import oauth, ratelimit
from tuckit.core.services.exceptions import LimitReached


def _ctx(raw):
    request = types.SimpleNamespace(headers={"authorization": f"Bearer {raw}"})
    return types.SimpleNamespace(request_context=types.SimpleNamespace(request=request))


@pytest.fixture(autouse=True)
def clean_buckets():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def tight_limits(settings):
    """A burst of 3 so a test can drain it in four calls. The connection layer
    only; the org layer gets its own test."""
    settings.TUCKIT_MCP_RATE_CONN_BURST = 3.0
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 1.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 0.0
    return settings


@sync_to_async
def _seed(org_slug="acme", email="a@b.co", client_name="Claude Code"):
    org = Org.objects.filter(slug=org_slug).first() or Org.objects.create(
        name=org_slug, slug=org_slug
    )
    user = get_user_model().objects.create_user(email=email, password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client = oauth.create_client(client_name, ["http://localhost/cb"])
    access, _refresh, _ttl = oauth.issue_tokens(client, user, org, "mcp")
    return access


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_connection_over_its_burst_is_refused(tight_limits):
    access = await _seed()
    for _ in range(3):
        await require_caller(_ctx(access))
    with pytest.raises(LimitReached) as exc:
        await require_caller(_ctx(access))
    assert "stop and report" in str(exc.value), (
        "the message must tell a looping agent to stop; retry guidance alone "
        "makes a runaway agent retry faster"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_one_blocked_connection_does_not_block_its_neighbour(tight_limits):
    """The headline reason the axis is per connection and not per org."""
    access_a = await _seed(email="a@b.co", client_name="Claude Code")
    access_b = await _seed(email="b@b.co", client_name="Codex")
    for _ in range(3):
        await require_caller(_ctx(access_a))
    with pytest.raises(LimitReached):
        await require_caller(_ctx(access_a))
    org, _user = await require_caller(_ctx(access_b))
    assert org.slug == "acme"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_org_backstop_refuses_even_when_connections_are_under_theirs(settings):
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 0.0
    settings.TUCKIT_MCP_RATE_ORG_BURST = 3.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 1.0
    access_a = await _seed(email="a@b.co", client_name="Claude Code")
    access_b = await _seed(email="b@b.co", client_name="Codex")
    await require_caller(_ctx(access_a))
    await require_caller(_ctx(access_b))
    await require_caller(_ctx(access_a))
    with pytest.raises(LimitReached):
        await require_caller(_ctx(access_b))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zero_per_sec_restores_the_old_behaviour(settings):
    """150 calls, not 50: the default connection burst is 120, so 50 calls
    would pass identically whether the limiter is off or simply active and
    under burst -- that would not prove "disabled". 150 exceeds the default
    burst on both layers, so an active limiter with default settings would
    definitely refuse somewhere in the loop.

    The bucket-emptiness assertion is the direct evidence: it proves
    `ratelimit.allow()` was never even called, not just that it never fired.
    Do not shrink the loop back down to make this test faster -- that
    silently restores the hole this test exists to close. Burst settings are
    deliberately left at their defaults; overriding them would undo the
    point.
    """
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 0.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 0.0
    access = await _seed()
    for _ in range(150):
        await require_caller(_ctx(access))
    assert ratelimit._buckets == {}
