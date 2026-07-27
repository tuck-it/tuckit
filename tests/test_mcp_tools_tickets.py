import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import (
    create_ticket, list_tickets, get_ticket, update_ticket, promote_ticket,
    absorb_ticket, release_ticket, get_slice,
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
    assert t["status"] == "open" and t["ref"] == "ACM-1"
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
    assert s["status"] == "open"
    assert await list_tickets(ctx) == []    # promoted -> leaves the inbox
    state = await get_project_state(ctx)
    assert state["inbox"]["open_count"] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_ticket_dismiss():
    _org, raw, _area_id = await _seed()
    ctx = make_ctx(raw)
    t = await create_ticket(ctx, "T")
    out = await update_ticket(ctx, t["id"], status="dismissed")
    assert out["status"] == "dismissed"
    assert await list_tickets(ctx) == []                       # left the Inbox
    assert len(await list_tickets(ctx, status="dismissed")) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_promoted_ticket_reports_live_slice_status_not_a_stored_copy():
    """The agent-facing half of the lifecycle change: a promoted ticket's own
    status stays 'promoted' forever, and "where did this end up" is answered by
    the slice it points at — so shipping and then reopening cannot make the two
    disagree."""
    from tuckit.core.services.slices import set_slice_status
    from tuckit.core.models import Slice

    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    t = await create_ticket(ctx, "OAuth screen is ugly", body="buttons misaligned")
    s = await promote_ticket(ctx, t["id"], area_id=area_id)

    listed = await list_tickets(ctx, status="promoted")
    assert listed[0]["status"] == "promoted"
    assert listed[0]["slice_status"] == "open"
    md = await get_ticket(ctx, t["id"])
    assert "Status: promoted → slice ACM-1 (open)" in md
    assert "buttons misaligned" in md          # captured context survived promotion

    slice_obj = await sync_to_async(Slice.objects.get)(pk=s["id"])
    await sync_to_async(set_slice_status)(slice_obj, "shipped")
    md = await get_ticket(ctx, t["id"])
    assert "Status: promoted → slice ACM-1 (shipped)" in md

    await sync_to_async(set_slice_status)(slice_obj, "open")   # reopened
    md = await get_ticket(ctx, t["id"])
    assert "Status: promoted → slice ACM-1 (open)" in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_absorb_and_release_round_trip_over_mcp():
    """The fold an agent actually performs during triage, end to end."""
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)

    parent = await create_ticket(ctx, "Parent", area_id=area_id)
    s = await promote_ticket(ctx, parent["id"])
    child = await create_ticket(ctx, "Child", body="a facet of the same thing", area_id=area_id)

    absorbed = await absorb_ticket(ctx, child["id"], s["ref"])
    assert absorbed["status"] == "promoted"
    assert absorbed["ref"] == child["ref"]          # keeps its own ref

    md = await get_slice(ctx, s["ref"])
    assert f"{parent['ref']} (origin)" in md
    assert child["ref"] in md
    # the body was never copied into the slice's spec
    assert "a facet of the same thing" not in md

    released = await release_ticket(ctx, child["id"])
    assert released["status"] == "open"
    md_after = await get_slice(ctx, s["ref"])
    assert child["ref"] not in md_after


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_promoted_slice_starts_with_an_empty_spec():
    """The blank spec is the signal an agent reads to decide whether the next
    step is designing or planning."""
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    t = await create_ticket(ctx, "Fix login", body="users get a 500", area_id=area_id)
    s = await promote_ticket(ctx, t["id"])

    md = await get_slice(ctx, s["ref"])
    assert "users get a 500" not in md      # not copied
    assert f"{t['ref']} (origin)" in md     # but reachable
    body = await get_ticket(ctx, t["id"])
    assert "users get a 500" in body        # the one copy still lives here
