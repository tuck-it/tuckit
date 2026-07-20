import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import create_area, list_areas
from tuckit.core.models import Org
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    return org, raw


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_and_list_areas():
    _org, raw = await _seed()
    ctx = make_ctx(raw)
    created = await create_area(ctx, "Backend", "the api")
    assert created["slug"] == "backend"
    areas = await list_areas(ctx)
    assert [a["name"] for a in areas] == ["Backend"]
