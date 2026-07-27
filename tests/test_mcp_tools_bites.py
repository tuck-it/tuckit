import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import (
    add_bites,
    list_bites,
    update_bite,
)
from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.plans import create_plan
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed_two_plans():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    area = create_area(org, "Backend")
    s = create_slice(area.org, area=area, title="Auth")
    p1 = create_plan(s, title="Plan one")
    p2 = create_plan(s, title="Plan two")
    return raw, p1.id, p2.id


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    area = create_area(org, "Backend")
    s = create_slice(area.org, area=area, title="Auth")
    p = create_plan(s, title="Plan")
    return raw, p.id, s.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bites_bulk_and_update_reorder():
    raw, plan_id, _slice_id = await _seed()
    ctx = make_ctx(raw)
    made = await add_bites(ctx, plan_id, [{"title": "A"}, {"title": "B"}])
    assert [b["title"] for b in made] == ["A", "B"]
    await update_bite(ctx, made[1]["id"], before_id=made[0]["id"])
    listed = await list_bites(ctx, plan_id)
    assert [x["title"] for x in listed] == ["B", "A"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_bite_status_and_body():
    raw, plan_id, _slice_id = await _seed()
    ctx = make_ctx(raw)
    (b,) = await add_bites(ctx, plan_id, [{"title": "JWT"}])
    await update_bite(ctx, b["id"], body="use RS256")
    updated = await update_bite(ctx, b["id"], status="done")
    assert updated["status"] == "done"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bites_returns_body_and_plan_id():
    raw, plan_id, slice_id = await _seed()
    ctx = make_ctx(raw)
    made = await add_bites(ctx, plan_id, [{"title": "JWT", "body": "use RS256 keys"}])
    listed = await list_bites(ctx, plan_id)
    assert listed[0]["body"] == "use RS256 keys"
    # create_bite() itself only ever attaches to the Slice now (Task 5), but
    # the add_bites MCP tool reparents each new bite onto plan_id afterward
    # (C2 fix) so it stays visible in a panel that's grouping by plan — so
    # plan_id on the response is still populated, same as before Task 5.
    assert made[0]["plan_id"] == plan_id
    assert made[0]["slice_id"] == slice_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_bites_returns_the_whole_slice_regardless_of_which_plan_id():
    """list_bites(plan_id) resolves plan_id one hop further to its slice and
    returns every bite on that slice (I1) — not just the ones reparented onto
    that particular plan. Two plans on one slice must therefore return the
    same full list."""
    raw, plan1_id, plan2_id = await _seed_two_plans()
    ctx = make_ctx(raw)
    await add_bites(ctx, plan1_id, [{"title": "from plan one"}])
    await add_bites(ctx, plan2_id, [{"title": "from plan two"}])

    via_plan1 = {b["title"] for b in await list_bites(ctx, plan1_id)}
    via_plan2 = {b["title"] for b in await list_bites(ctx, plan2_id)}

    assert via_plan1 == via_plan2 == {"from plan one", "from plan two"}
