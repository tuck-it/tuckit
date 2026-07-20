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
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    area = create_area(org, "Backend")
    s = create_slice(area, "Auth")
    p = create_plan(s, title="Plan")
    return raw, p.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bites_bulk_and_update_reorder():
    raw, plan_id = await _seed()
    ctx = make_ctx(raw)
    made = await add_bites(ctx, plan_id, [{"title": "A"}, {"title": "B"}])
    assert [b["title"] for b in made] == ["A", "B"]
    await update_bite(ctx, made[1]["id"], before_id=made[0]["id"])
    listed = await list_bites(ctx, plan_id)
    assert [x["title"] for x in listed] == ["B", "A"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_bite_status_and_body():
    raw, plan_id = await _seed()
    ctx = make_ctx(raw)
    (b,) = await add_bites(ctx, plan_id, [{"title": "JWT"}])
    await update_bite(ctx, b["id"], body="use RS256")
    updated = await update_bite(ctx, b["id"], status="done")
    assert updated["status"] == "done"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bites_returns_body_and_plan_id():
    raw, plan_id = await _seed()
    ctx = make_ctx(raw)
    made = await add_bites(ctx, plan_id, [{"title": "JWT", "body": "use RS256 keys"}])
    listed = await list_bites(ctx, plan_id)
    assert listed[0]["body"] == "use RS256 keys"
    assert made[0]["plan_id"] == plan_id
