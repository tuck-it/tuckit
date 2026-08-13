import types

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from tuckit.core.mcp.auth import _connection
from tuckit.core.models import Org, OrgMember
from tuckit.core.services import oauth
from tuckit.core.services.tokens import generate_token


@sync_to_async
def _seed_oauth():
    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="a@b.co", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client = oauth.create_client("Claude Code", ["http://localhost/cb"])
    access, refresh, _ttl = oauth.issue_tokens(client, user, org, "mcp")
    return access, refresh


@sync_to_async
def _seed_legacy():
    org = Org.objects.create(name="Legacy", slug="legacy")
    token, raw = generate_token(org, "t")
    return raw, token.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_oauth_connection_carries_org_user_key_and_label():
    access, _refresh = await _seed_oauth()
    conn = await sync_to_async(_connection)(access)
    assert conn.org.slug == "acme"
    assert conn.user.email == "a@b.co"
    assert conn.label == "Claude Code · a@b.co"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_key_survives_access_token_rotation():
    """The whole reason the key is not the token. An access token lives an hour
    and rotates on refresh; if the bucket were keyed on it, every refresh would
    hand a looping agent a clean bucket."""
    access, refresh = await _seed_oauth()
    before = await sync_to_async(_connection)(access)
    rotated = await sync_to_async(oauth.rotate_refresh_token)(refresh)
    new_access = rotated[0]
    after = await sync_to_async(_connection)(new_access)
    assert new_access != access
    assert before.key == after.key
    assert before.label == after.label


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_connections_in_one_org_get_different_keys():
    """One broken agent must not be able to drain another agent's budget."""
    access_a, _ = await _seed_oauth()
    conn_a = await sync_to_async(_connection)(access_a)

    @sync_to_async
    def _second_client(org, user):
        client = oauth.create_client("Codex", ["http://localhost/cb"])
        access, _r, _t = oauth.issue_tokens(client, user, org, "mcp")
        return access

    access_b = await _second_client(conn_a.org, conn_a.user)
    conn_b = await sync_to_async(_connection)(access_b)
    assert conn_a.org.id == conn_b.org.id
    assert conn_a.key != conn_b.key


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_legacy_api_token_has_no_user_and_keys_on_its_pk():
    raw, token_id = await _seed_legacy()
    conn = await sync_to_async(_connection)(raw)
    assert conn.org.slug == "legacy"
    assert conn.user is None
    assert conn.key == ("apitoken", token_id)
    assert conn.label == f"API token #{token_id}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unknown_bearer_resolves_to_nothing():
    assert await sync_to_async(_connection)("not-a-real-token") is None
