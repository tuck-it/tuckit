import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import (
    add_bites,
    list_bites,
    update_bite,
)
from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    area = create_area(org, "Backend")
    s = create_slice(area.org, area=area, title="Auth")
    return raw, s.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bites_bulk_and_update_reorder():
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)
    made = await add_bites(ctx, slice_id, [{"title": "A"}, {"title": "B"}])
    assert [b["title"] for b in made] == ["A", "B"]
    await update_bite(ctx, made[1]["id"], before_id=made[0]["id"])
    listed = await list_bites(ctx, slice_id)
    assert [x["title"] for x in listed] == ["B", "A"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_bite_status_and_body():
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)
    (b,) = await add_bites(ctx, slice_id, [{"title": "JWT"}])
    await update_bite(ctx, b["id"], body="use RS256")
    updated = await update_bite(ctx, b["id"], status="done")
    assert updated["status"] == "done"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bites_takes_a_slice_id():
    """Both bite tools address the slice directly. There is no plan_id to
    resolve one hop through any more — the parameter is gone, not renamed."""
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)

    made = await add_bites(ctx, slice_id=slice_id, bites=[{"title": "JWT", "body": "use RS256 keys"}])

    assert made[0]["slice_id"] == slice_id
    listed = await list_bites(ctx, slice_id=slice_id)
    assert len(listed) == 1
    assert listed[0]["body"] == "use RS256 keys"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_bite_dict_does_not_name_the_plan_layer():
    """The serialized bite is the only description of a step an agent ever
    sees. A `plan_id` key would keep a retired concept alive in exactly the
    vocabulary this release set out to shrink."""
    raw, slice_id = await _seed()
    ctx = make_ctx(raw)

    (made,) = await add_bites(ctx, slice_id, [{"title": "JWT"}])

    assert "plan_id" not in made
    assert "plan_id" not in (await list_bites(ctx, slice_id))[0]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bites_rejects_a_slice_from_another_org():
    from tuckit.core.services.exceptions import NotFound

    @sync_to_async
    def other_token():
        other = Org.objects.create(name="Other", slug="other")
        _, raw = generate_token(other, "t2")
        return raw

    _raw, slice_id = await _seed()
    raw2 = await other_token()

    with pytest.raises(NotFound):
        await add_bites(make_ctx(raw2), slice_id, [{"title": "X"}])
