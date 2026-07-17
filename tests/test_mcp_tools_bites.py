import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import (
    create_bite,
    list_bites,
    reorder_bite,
    set_bite_status,
    update_bite,
)
from tuckit.core.models import Org, Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.plans import create_plan
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="P", slug="p")
    _, raw = generate_token(ws, "t")
    area = create_area(ws.org, "Backend")
    s = create_slice(area, "Auth")
    p = create_plan(s, title="Plan")
    return raw, p.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_list_reorder_bites():
    raw, plan_id = await _seed()
    ctx = make_ctx(raw)
    a = await create_bite(ctx, plan_id, "A")
    b = await create_bite(ctx, plan_id, "B")
    await reorder_bite(ctx, b["id"], before_id=a["id"])
    listed = await list_bites(ctx, plan_id)
    assert [x["title"] for x in listed] == ["B", "A"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_and_status_bite():
    raw, plan_id = await _seed()
    ctx = make_ctx(raw)
    b = await create_bite(ctx, plan_id, "JWT")
    await update_bite(ctx, b["id"], body="use RS256")
    updated = await set_bite_status(ctx, b["id"], "done")
    assert updated["status"] == "done"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_bites_returns_body():
    raw, plan_id = await _seed()
    ctx = make_ctx(raw)
    await create_bite(ctx, plan_id, "JWT", body="use RS256 keys")
    listed = await list_bites(ctx, plan_id)
    assert listed[0]["body"] == "use RS256 keys"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_bite_exposes_plan_id():
    raw, plan_id = await _seed()
    ctx = make_ctx(raw)
    b = await create_bite(ctx, plan_id, "JWT")
    assert b["plan_id"] == plan_id
