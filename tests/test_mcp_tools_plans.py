import pytest
from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import get_slice, set_plan
from tuckit.core.models import Org, Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="P", slug="p")
    _, raw = generate_token(ws, "t")
    s = create_slice(create_area(ws, "Backend"), "Auth")
    return raw, s.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_set_plan_tool_writes_and_get_slice_reads():
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)
    md = await set_plan(ctx, slice_id, body="Goal: X", constraints="no billing")
    assert "## Plan" in md and "Goal: X" in md and "no billing" in md
    md2 = await get_slice(ctx, slice_id)
    assert "## Plan" in md2 and "Goal: X" in md2
