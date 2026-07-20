import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import (
    create_slice,
    get_slice,
    list_slices,
    update_slice,
)
from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.exceptions import InvalidValue, NotFound
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    # Org is the tenant boundary (resolve.get_area/etc are org-scoped), so
    # cross-tenant rejection must be tested across orgs.
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    _, raw = generate_token(org, "t")
    area = create_area(org, "Backend")
    return org, other_org, raw, area.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_list_and_render_slice():
    _org, _other_org, raw, area_id = await _seed()
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
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    a = await create_slice(ctx, area_id, "A")
    b = await create_slice(ctx, area_id, "B")
    await update_slice(ctx, b["id"], before_id=a["id"])
    listed = await list_slices(ctx, area_id)
    assert [x["title"] for x in listed] == ["B", "A"]
    await update_slice(ctx, a["id"], status="shipped")
    await update_slice(ctx, a["id"], title="A2")
    md = await get_slice(ctx, a["id"])
    assert "# A2" in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_bad_status_rejected():
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    with pytest.raises(InvalidValue):
        await create_slice(ctx, area_id, "X", status="blocked")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cross_org_area_rejected():
    _org, other_org, _raw, area_id = await _seed()

    @sync_to_async
    def other_token():
        _, raw = generate_token(other_org, "t2")
        return raw

    raw2 = await other_token()
    with pytest.raises(NotFound):
        await create_slice(make_ctx(raw2), area_id, "X")  # area belongs to org, not other_org


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_slice_accepts_ref_and_dict_has_ref():
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, area_id, "Auth", spec="x")
    assert s["ref"].startswith("acme-")
    md = await get_slice(ctx, s["ref"])
    assert "# Auth" in md
    md2 = await get_slice(ctx, s["ref"], with_activity=True)
    assert "## Activity" in md2
