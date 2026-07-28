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
    s = await create_slice(ctx, "Auth", area_id=area_id, spec="OAuth login.", status="shipped", tags=["feature"])
    assert s["status"] == "shipped"
    listed = await list_slices(ctx, area_id)
    assert [x["title"] for x in listed] == ["Auth"]
    md = await get_slice(ctx, s["id"])
    assert "# Auth" in md and "OAuth login." in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_status_and_reorder():
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    a = await create_slice(ctx, "A", area_id=area_id)
    b = await create_slice(ctx, "B", area_id=area_id)
    await update_slice(ctx, b["id"], before_id=a["id"])
    listed = await list_slices(ctx, area_id)
    assert [x["title"] for x in listed] == ["B", "A"]
    await update_slice(ctx, a["id"], status="shipped")
    await update_slice(ctx, a["id"], title="A2")
    md = await get_slice(ctx, a["id"])
    assert "# A2" in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_slice_defaults_to_open():
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)

    s = await create_slice(ctx, "New work", area_id=area_id)

    assert s["status"] == "open"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_slice_rejects_retired_status():
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "New work", area_id=area_id)

    with pytest.raises(InvalidValue):
        await update_slice(ctx, s["id"], status="building")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_bad_status_rejected():
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    with pytest.raises(InvalidValue):
        await create_slice(ctx, "X", area_id=area_id, status="blocked")


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
        await create_slice(make_ctx(raw2), "X", area_id=area_id)  # area belongs to org, not other_org


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_slice_accepts_ref_and_dict_has_ref():
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Auth", area_id=area_id, spec="x")
    assert s["ref"].startswith("ACM-")
    md = await get_slice(ctx, s["ref"])
    assert "# Auth" in md
    md2 = await get_slice(ctx, s["ref"], with_activity=True)
    assert "## Activity" in md2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_slices_search_without_area():
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    await create_slice(ctx, "Auth login", area_id=area_id)
    await create_slice(ctx, "Payments", area_id=area_id)
    hits = await list_slices(ctx, query="login")   # no area_id -> org-wide
    assert [s["title"] for s in hits] == ["Auth login"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_slices_rows_carry_stage():
    """The complaint this answers: an agent could not tell from the list which
    slice it was able to act on, and had to open every one."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    await create_slice(ctx, "Blank", area_id=area_id)
    await create_slice(ctx, "Designed", area_id=area_id, spec="a real design doc")

    rows = {r["title"]: r for r in await list_slices(ctx)}
    assert rows["Blank"]["stage"] == "needs_design"
    assert rows["Designed"]["stage"] == "needs_steps"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_write_paths_do_not_report_stage():
    """Deliberate omission (design D3): create/update already know what they
    just wrote, and re-deriving costs two queries to say so. Pinned so it cannot
    come back by accident through slice_dict."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    created = await create_slice(ctx, "New", area_id=area_id)
    updated = await update_slice(ctx, created["id"], title="Renamed")

    assert "stage" not in created
    assert "stage" not in updated


# --- the Inbox, reachable from MCP at last -------------------------------
#
# Before this task an agent could not touch the Inbox at all: create_slice
# REQUIRED an area, list_slices inherited query_slices' filed-only default,
# and no tool listed area-less work. On production that was ~28 captures no
# agent could see. These pin all three doors open.


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_slice_without_area_lands_in_inbox():
    """Capturing without filing is a first-class path — an agent that knows
    something matters must not have to invent an area to record it."""
    from tuckit.core.models import Slice

    _org, _other, raw, _area_id = await _seed()

    s = await create_slice(make_ctx(raw), title="에이전트 캡처")

    got = await sync_to_async(Slice.objects.get)(id=s["id"])
    assert got.area_id is None
    assert s["area_id"] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_slices_without_an_area_includes_the_inbox():
    """The org-wide list is the whole org. query_slices' service default hides
    area-less slices because the Board cannot render them; an agent inheriting
    that default is blind to every untriaged capture."""
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    await create_slice(ctx, "filed", area_id=area_id)
    await create_slice(ctx, "unfiled")

    titles = {row["title"] for row in await list_slices(ctx)}

    assert titles == {"filed", "unfiled"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_slices_can_ask_for_the_inbox_alone():
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    await create_slice(ctx, "filed", area_id=area_id)
    await create_slice(ctx, "unfiled")

    rows = await list_slices(ctx, area_id="")

    assert [r["title"] for r in rows] == ["unfiled"]
    assert rows[0]["area_id"] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_filing_and_unfiling_a_slice_are_both_reachable():
    """Triage is picking an area, and un-triage is un-picking one. Neither is a
    one-way door — that symmetry is the release's whole claim, and it has to
    hold on the agent surface too, not just in the web UI."""
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "capture")

    filed = await update_slice(ctx, s["id"], area_id=area_id)
    assert filed["area_id"] == area_id

    back = await update_slice(ctx, s["id"], area_id="")
    assert back["area_id"] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_omitting_area_id_on_update_leaves_the_area_alone():
    """`None` means 'not mentioned', not 'clear it' — otherwise every title
    edit would silently un-file the slice."""
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "filed", area_id=area_id)

    renamed = await update_slice(ctx, s["id"], title="renamed")

    assert renamed["area_id"] == area_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_constraints_round_trip_through_create_and_get():
    """Constraints is what a later agent must not get wrong. It is only worth
    anything if the agent that writes it and the agent that reads it use the
    same surface — create_slice writes, get_slice renders."""
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)

    s = await create_slice(
        ctx, "Auth", area_id=area_id, spec="design",
        constraints="hx-swap을 명시할 것 — 아니면 200이 조용히 버려진다.",
    )

    md = await get_slice(ctx, s["id"])
    assert "## Constraints" in md
    assert "hx-swap을 명시할 것" in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_slice_can_write_constraints():
    _org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Auth", area_id=area_id, spec="design")

    await update_slice(ctx, s["id"], constraints="never touch billing")

    assert "never touch billing" in await get_slice(ctx, s["id"])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_area_name_in_area_id_says_what_to_do():
    """The likeliest agent mistake on this parameter is passing the area's
    NAME. int() would raise ValueError out of the middle of the tool and reach
    the caller as an opaque failure; the message has to name the fix."""
    _org, _other, raw, _area_id = await _seed()

    with pytest.raises(InvalidValue) as e:
        await create_slice(make_ctx(raw), "X", area_id="Backend")

    assert "list_areas" in str(e.value)
