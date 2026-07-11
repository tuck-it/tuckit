import pytest

from asgiref.sync import sync_to_async

from core.mcp.server import (
    create_bite,
    list_bites,
    reorder_bite,
    set_bite_status,
    update_bite,
)
from core.models import Org, Workspace
from core.services.areas import create_area
from core.services.slices import create_slice
from core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="P", slug="p")
    _, raw = generate_token(ws, "t")
    area = create_area(ws, "Backend")
    s = create_slice(area, "Auth")
    return raw, s.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_list_reorder_bites():
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)
    a = await create_bite(ctx, slice_id, "A")
    b = await create_bite(ctx, slice_id, "B")
    await reorder_bite(ctx, b["id"], before_id=a["id"])
    listed = await list_bites(ctx, slice_id)
    assert [x["title"] for x in listed] == ["B", "A"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_and_status_bite():
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)
    b = await create_bite(ctx, slice_id, "JWT")
    await update_bite(ctx, b["id"], body="use RS256")
    updated = await set_bite_status(ctx, b["id"], "done")
    assert updated["status"] == "done"
