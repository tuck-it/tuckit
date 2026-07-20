import types

import pytest

from tuckit.core.mcp.server import get_project_state
from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tokens import generate_token


def make_ctx(raw_token: str):
    """Build a fake MCP Context exposing request headers, matching the real
    ctx.request_context.request.headers accessor the tool relies on."""
    request = types.SimpleNamespace(headers={"authorization": f"Bearer {raw_token}"})
    request_context = types.SimpleNamespace(request=request)
    return types.SimpleNamespace(request_context=request_context)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_project_state_tool_returns_state():
    org = await _make_org()
    _, raw = await _make_token(org)
    result = await get_project_state(make_ctx(raw))
    assert result["org"]["name"] == "Acme"
    assert [a["shipped"][0]["title"] for a in result["areas"]] == ["Auth"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_project_state_tool_rejects_bad_token():
    from tuckit.core.services.exceptions import NotFound

    await _make_org()
    with pytest.raises(NotFound):
        await get_project_state(make_ctx("bogus-token"))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_project_state_includes_caller_identity_legacy_token():
    org = await _make_org()
    _, raw = await _make_token(org)  # legacy ApiToken -> no user
    result = await get_project_state(make_ctx(raw))
    assert result["caller"]["org_slug"] == "acme"
    assert result["caller"]["user_email"] is None


# --- async helpers (ORM access wrapped for the async test) ---
from asgiref.sync import sync_to_async  # noqa: E402


@sync_to_async
def _make_org():
    org = Org.objects.create(name="Acme", slug="acme", description="demo")
    area = create_area(org, "Backend")
    create_slice(area, "Auth", status="shipped")
    return org


@sync_to_async
def _make_token(org):
    return generate_token(org, "test")
