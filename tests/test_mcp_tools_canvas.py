import pytest
from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import create_slice, propose, update_slice
from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    return org, raw, create_area(org, "Backend").id


@sync_to_async
def _draft_ids(slice_id):
    return [n["id"] for n in Slice.objects.get(id=slice_id).draft.get("nodes", [])]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_propose_puts_nodes_on_the_canvas():
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id)

    out = await propose(ctx, s["id"], [
        {"id": "q1", "parent": None, "kind": "question", "title": "Where does it live?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "On the slice",
         "summary": "one field, no new model", "recommended": True},
    ])

    assert out["count"] == 2
    assert out["node_ids"] == ["q1", "o1"]
    assert await _draft_ids(s["id"]) == ["q1", "o1"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_writing_the_spec_over_mcp_retires_the_canvas():
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id)
    await propose(ctx, s["id"], [
        {"id": "q1", "parent": None, "kind": "question", "title": "Q"}])

    await update_slice(ctx, s["id"], spec="## Decision\nOn the slice.")

    assert await _draft_ids(s["id"]) == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_propose_refuses_once_the_design_is_written():
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id, spec="## Done\ntext")

    with pytest.raises(InvalidValue):
        await propose(ctx, s["id"], [
            {"id": "q1", "parent": None, "kind": "note", "title": "Q"}])
