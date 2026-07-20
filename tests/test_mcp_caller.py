import types

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from tuckit.core.models import Org, OrgMember
from tuckit.core.services import oauth
from tuckit.core.services.tokens import generate_token
from tuckit.core.mcp.auth import require_caller


def _ctx(raw):
    request = types.SimpleNamespace(headers={"authorization": f"Bearer {raw}"})
    return types.SimpleNamespace(request_context=types.SimpleNamespace(request=request))


@sync_to_async
def _seed_oauth():
    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="a@b.co", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client = oauth.create_client("cli", ["http://localhost/cb"])
    access, _refresh, _ttl = oauth.issue_tokens(client, user, org, "mcp")
    return access


@sync_to_async
def _seed_legacy():
    org = Org.objects.create(name="Legacy", slug="legacy")
    _, raw = generate_token(org, "t")
    return raw


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_require_caller_returns_user_for_oauth():
    access = await _seed_oauth()
    org, user = await require_caller(_ctx(access))
    assert org.slug == "acme" and user.email == "a@b.co"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_require_caller_user_none_for_legacy_token():
    raw = await _seed_legacy()
    org, user = await require_caller(_ctx(raw))
    assert org.slug == "legacy" and user is None
