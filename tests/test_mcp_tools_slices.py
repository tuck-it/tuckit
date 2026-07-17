import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import (
    create_slice,
    get_slice,
    list_slices,
    reorder_slice,
    set_slice_status,
    update_slice,
)
from tuckit.core.models import Org, Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.exceptions import InvalidValue, NotFound
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="P", slug="p")
    # A different org, not just a different workspace: Org is now the tenant
    # boundary (Task 5 moves resolve.get_area/etc to org-scoped lookups), so
    # cross-tenant rejection must be tested across orgs, not sibling
    # workspaces of the same org.
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="O", slug="o")
    _, raw = generate_token(ws, "t")
    area = create_area(ws.org, "Backend")
    return ws, other, raw, area.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_list_and_render_slice():
    _ws, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, area_id, "Auth", spec="OAuth login.", status="building", tags=["feature"])
    assert s["status"] == "building"
    listed = await list_slices(ctx, area_id)
    assert [x["title"] for x in listed] == ["Auth"]
    md = await get_slice(ctx, s["id"])
    assert "# Auth" in md and "OAuth login." in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_status_and_reorder():
    _ws, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    a = await create_slice(ctx, area_id, "A")
    b = await create_slice(ctx, area_id, "B")
    await reorder_slice(ctx, b["id"], before_id=a["id"])
    listed = await list_slices(ctx, area_id)
    assert [x["title"] for x in listed] == ["B", "A"]
    await set_slice_status(ctx, a["id"], "shipped")
    await update_slice(ctx, a["id"], title="A2")
    md = await get_slice(ctx, a["id"])
    assert "# A2" in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_bad_status_rejected():
    _ws, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    with pytest.raises(InvalidValue):
        await create_slice(ctx, area_id, "X", status="blocked")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cross_workspace_area_rejected():
    _ws, other, _raw, area_id = await _seed()

    @sync_to_async
    def other_token():
        _, raw = generate_token(other, "t2")
        return raw

    raw2 = await other_token()
    with pytest.raises(NotFound):
        await create_slice(make_ctx(raw2), area_id, "X")  # area belongs to ws, not other
