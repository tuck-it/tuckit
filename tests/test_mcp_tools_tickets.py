import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import (
    create_ticket, list_tickets, get_ticket, update_ticket, promote_ticket,
    get_project_state,
)
from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    area = create_area(org, "Backend")
    return org, raw, area.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_list_and_get_ticket():
    _org, raw, _area_id = await _seed()
    ctx = make_ctx(raw)
    t = await create_ticket(ctx, "Fix login", body="from brainstorm")
    assert t["status"] == "open" and t["ref"] == "acme-1"
    listed = await list_tickets(ctx)
    assert [x["title"] for x in listed] == ["Fix login"]
    md = await get_ticket(ctx, t["id"])
    assert "# Fix login" in md and "from brainstorm" in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_promote_ticket_and_inbox_shrinks():
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    t = await create_ticket(ctx, "Fix login")
    s = await promote_ticket(ctx, t["id"], area_id=area_id)
    assert s["ref"] == t["ref"]            # inherits the number
    assert s["status"] == "planned"
    assert await list_tickets(ctx) == []    # promoted -> leaves the inbox
    state = await get_project_state(ctx)
    assert state["inbox"]["open_count"] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_ticket_close():
    _org, raw, _area_id = await _seed()
    ctx = make_ctx(raw)
    t = await create_ticket(ctx, "T")
    await update_ticket(ctx, t["id"], status="closed")
    assert await list_tickets(ctx) == []
