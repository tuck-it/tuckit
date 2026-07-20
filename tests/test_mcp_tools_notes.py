import pytest
from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import add_note, get_slice, create_slice
from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    return raw, create_area(org, "B").id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_note_then_get_slice_with_activity():
    raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, area_id, "Auth")
    ev = await add_note(ctx, s["id"], "blocked on Neon migration")
    assert ev["verb"] == "noted" and ev["body"] == "blocked on Neon migration"
    md = await get_slice(ctx, s["ref"], with_activity=True)
    assert "blocked on Neon migration" in md
