import types

import pytest

from tuckit.core.mcp.server import get_project_state
from tuckit.core.models import Org, Workspace
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
    ws = await _make_ws()
    _, raw = await _make_token(ws)
    result = await get_project_state(make_ctx(raw))
    assert result["product"]["name"] == "MyProduct"
    assert [a["shipped"][0]["title"] for a in result["areas"]] == ["Auth"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_project_state_tool_rejects_bad_token():
    from tuckit.core.services.exceptions import NotFound

    await _make_ws()
    with pytest.raises(NotFound):
        await get_project_state(make_ctx("bogus-token"))


# --- async helpers (ORM access wrapped for the async test) ---
from asgiref.sync import sync_to_async  # noqa: E402


@sync_to_async
def _make_ws():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="MyProduct", slug="myproduct", description="demo")
    area = create_area(ws, "Backend")
    create_slice(area, "Auth", status="shipped")
    return ws


@sync_to_async
def _make_token(ws):
    return generate_token(ws, "test")
