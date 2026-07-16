import pytest
from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import create_bite, create_plan, get_slice, list_plans, update_plan
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
async def test_create_plan_list_plans_create_bite_get_slice_roundtrip():
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)

    plan = await create_plan(ctx, slice_id, title="Backend plan", body="Goal: X", constraints="no billing")
    assert plan["title"] == "Backend plan"
    assert plan["slice_id"] == slice_id
    assert plan["body"] == "Goal: X"
    assert plan["constraints"] == "no billing"

    plans = await list_plans(ctx, slice_id)
    assert [p["title"] for p in plans] == ["Backend plan"]

    bite = await create_bite(ctx, plan["id"], "JWT")
    assert bite["plan_id"] == plan["id"]
    assert bite["slice_id"] == slice_id

    md = await get_slice(ctx, slice_id)
    assert "## Backend plan" in md
    assert "Goal: X" in md
    assert "### Constraints" in md and "no billing" in md
    assert "- [ ] JWT" in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_plan_tool():
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)
    plan = await create_plan(ctx, slice_id, title="Plan")

    updated = await update_plan(ctx, plan["id"], body="new body", constraints="be careful")
    assert updated["body"] == "new body"
    assert updated["constraints"] == "be careful"
    assert updated["title"] == "Plan"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_plans_returns_every_plan_for_slice():
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)
    await create_plan(ctx, slice_id, title="Backend plan")
    await create_plan(ctx, slice_id, title="Frontend plan")

    plans = await list_plans(ctx, slice_id)
    assert [p["title"] for p in plans] == ["Backend plan", "Frontend plan"]
