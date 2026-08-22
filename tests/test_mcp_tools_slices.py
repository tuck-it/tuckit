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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_inbox_is_the_same_set_from_every_surface():
    """get_project_state()['inbox'] and list_slices(area_id='') must return the
    same slices. An agent reads the count from the first at session start and
    then works through the second — if they disagree it is chasing a number it
    can never reach, and neither surface admits the difference.

    They disagreed before this fix: get_project_state used inbox_slices()
    (unfiled AND open) while list_slices' inbox branch filtered on area alone,
    so any capture shipped or dropped before triage showed up in one and not
    the other. Both go through inbox_filter() now."""
    from tuckit.core.services.state import get_project_state

    org, _other, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    await create_slice(ctx, "still waiting")
    await create_slice(ctx, "filed", area_id=area_id)
    dropped = await create_slice(ctx, "dropped before triage")
    await update_slice(ctx, dropped["id"], status="dropped")

    listed = {row["title"] for row in await list_slices(ctx, area_id="")}
    state = await sync_to_async(get_project_state)(org)

    assert listed == {"still waiting"}
    assert state["inbox"]["open_count"] == len(listed)
    assert {row["title"] for row in state["inbox"]["recent"]} == listed


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unfiled_dropped_capture_is_still_reachable_without_the_inbox():
    """Narrowing the Inbox to open-only must not strand anything: dropping
    `area_id` searches the whole org, unfiled work included, so a capture
    dropped before triage is one `status` filter away."""
    _org, _other, raw, _area_id = await _seed()
    ctx = make_ctx(raw)
    dropped = await create_slice(ctx, "dropped before triage")
    await update_slice(ctx, dropped["id"], status="dropped")

    rows = await list_slices(ctx, status="dropped")

    assert [r["title"] for r in rows] == ["dropped before triage"]
    assert rows[0]["area_id"] is None


@sync_to_async
def _seed_oauth_caller():
    """An OAuth token, i.e. an agent acting on behalf of a real person."""
    from django.contrib.auth import get_user_model
    from tuckit.core.models import OrgMember
    from tuckit.core.services import oauth

    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="human@example.com", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client = oauth.create_client("cli", ["http://localhost/cb"])
    access, _refresh, _ttl = oauth.issue_tokens(client, user, org, "mcp")
    return org, access


@sync_to_async
def _created_by_email(slice_id):
    from tuckit.core.models import Slice
    s = Slice.objects.select_related("created_by__user").get(pk=slice_id)
    return s.created_by.user.email if s.created_by_id else None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_slice_records_the_oauth_caller_as_capturer():
    """`source="agent"` only says human-vs-agent. An OAuth token knows WHICH
    human the agent is acting for, and the panel's "Captured by" reads that."""
    _org, access = await _seed_oauth_caller()
    s = await create_slice(make_ctx(access), "From my agent")
    assert await _created_by_email(s["id"]) == "human@example.com"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_slice_with_a_machine_token_records_no_capturer():
    """A legacy/machine token resolves to no user, so there is nobody to name —
    the UI falls back to `source`."""
    _org, _other, raw, _area_id = await _seed()
    s = await create_slice(make_ctx(raw), "From a headless agent")
    assert await _created_by_email(s["id"]) is None


# --- the agent-facing board gets a time axis (TP-252) --------------------
#
# Every field below existed on the model and reached nobody: an agent could
# not tell a five-minute-old capture from a forty-day-old one, so nothing on
# its board ever looked stale -- while that same agent was doing most of the
# adding. 140 open slices, 109 of them closed unread in one pass, is what that
# blindness cost.


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_slice_rows_carry_age_and_idle_days():
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    await create_slice(ctx, "Fresh", area_id=area_id)

    row = (await list_slices(ctx, area_id))[0]

    assert row["age_days"] == 0
    assert row["idle_days"] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_age_days_counts_from_creation_not_from_the_last_edit():
    """The two numbers answer different questions. A slice reopened and
    rewritten every week is young by idle_days and old by age_days, and it is
    the second one that says "we have been carrying this since June"."""
    from datetime import timedelta

    from django.utils import timezone

    from tuckit.core.models import Slice

    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    created = await create_slice(ctx, "Carried", area_id=area_id)

    # auto_now_add/auto_now ignore assignment, so both columns are moved with
    # an UPDATE that bypasses save().
    @sync_to_async
    def _backdate():
        now = timezone.now()
        Slice.objects.filter(id=created["id"]).update(
            created_at=now - timedelta(days=40), updated_at=now - timedelta(days=7),
        )

    await _backdate()

    row = (await list_slices(ctx, area_id))[0]

    assert row["age_days"] == 40
    assert row["idle_days"] == 7


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_one_response_measures_every_row_from_the_same_instant():
    """Reading the clock per row makes a long list disagree with itself, and a
    test that only checks one row would never see it. Pinned by handing the
    serializer an explicit `now` and proving the tool does the same."""
    from datetime import timedelta

    from django.utils import timezone

    from tuckit.core.mcp.serializers import slice_dict
    from tuckit.core.models import Slice

    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    for title in ("A", "B", "C"):
        await create_slice(ctx, title, area_id=area_id)

    @sync_to_async
    def _serialize_with_a_fixed_clock():
        now = timezone.now() + timedelta(days=10)
        return [slice_dict(s, now=now) for s in Slice.objects.all()]

    rows = await _serialize_with_a_fixed_clock()

    assert {r["age_days"] for r in rows} == {10}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_write_paths_report_the_time_axis_too():
    """create/update deliberately omit `stage` (see above), but not these: a
    caller that just filed something is exactly who should see that the thing
    it duplicated has been sitting there for a month."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)

    created = await create_slice(ctx, "New", area_id=area_id)
    updated = await update_slice(ctx, created["id"], title="Renamed")

    assert created["age_days"] == 0 and created["idle_days"] == 0
    assert updated["age_days"] == 0 and updated["idle_days"] == 0


# --- the way out costs what the way in cost (TP-254) ---------------------
#
# add_bites and propose take lists; nothing that closes anything did. Clearing
# 109 slices took 109 calls, while creating them had been one-at-a-time over
# forty days where each felt free. The asymmetry was in the type signature.


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_one_call_closes_many_slices():
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    ids = [(await create_slice(ctx, f"S{i}", area_id=area_id))["id"] for i in range(5)]

    rows = await update_slice(ctx, ids, status="dropped")

    assert [r["status"] for r in rows] == ["dropped"] * 5
    assert {r["title"] for r in rows} == {f"S{i}" for i in range(5)}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_single_id_still_returns_a_bare_dict():
    """Every existing caller passes an int. Wrapping that in a list would break
    all of them at once."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    created = await create_slice(ctx, "Solo", area_id=area_id)

    updated = await update_slice(ctx, created["id"], status="shipped")

    assert isinstance(updated, dict) and updated["status"] == "shipped"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_batch_files_and_unfiles_too():
    """area_id is the other reversible decision, so triage is a batch as well."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    ids = [(await create_slice(ctx, f"Capture {i}"))["id"] for i in range(3)]

    filed = await update_slice(ctx, ids, area_id=area_id)
    assert [r["area_id"] for r in filed] == [area_id] * 3

    back = await update_slice(ctx, ids, area_id="")
    assert [r["area_id"] for r in back] == [None] * 3


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["title", "spec", "constraints"])
async def test_a_batch_refuses_to_write_body_text(field):
    """The failure this forecloses: one body written across many slices, with
    no way back. It is the shape that already destroyed a decision record once
    (TP-238), so it is refused rather than partially applied."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    ids = [(await create_slice(ctx, f"S{i}", area_id=area_id, spec="original"))["id"]
           for i in range(2)]

    with pytest.raises(InvalidValue):
        await update_slice(ctx, ids, **{field: "overwritten"})


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_refused_batch_leaves_every_slice_untouched():
    """Refusing is only worth anything if it happens before the first write."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    ids = [(await create_slice(ctx, f"S{i}", area_id=area_id, spec="original"))["id"]
           for i in range(2)]

    with pytest.raises(InvalidValue):
        await update_slice(ctx, ids, status="dropped", spec="overwritten")

    for sid in ids:
        md = await get_slice(ctx, sid)
        assert "original" in md and "Status: open" in md


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unknown_id_fails_the_whole_batch():
    """Partial success would leave nobody able to say how many closed."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    good = [(await create_slice(ctx, f"S{i}", area_id=area_id))["id"] for i in range(3)]

    with pytest.raises(NotFound):
        await update_slice(ctx, good + [999_999], status="dropped")

    for sid in good:
        assert "Status: open" in await get_slice(ctx, sid)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_batch_is_bounded_and_rejects_duplicates_and_emptiness():
    from tuckit.core.mcp.server import BATCH_LIMIT

    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    one = (await create_slice(ctx, "S", area_id=area_id))["id"]

    with pytest.raises(InvalidValue):
        await update_slice(ctx, [], status="dropped")
    with pytest.raises(InvalidValue):
        await update_slice(ctx, [one, one], status="dropped")
    with pytest.raises(InvalidValue):
        await update_slice(ctx, list(range(BATCH_LIMIT + 1)), status="dropped")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_every_slice_in_a_batch_keeps_its_own_activity_row():
    """A batch collapsed into one event would erase, from each slice's own
    history, the moment it was closed."""
    _org, _other_org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    ids = [(await create_slice(ctx, f"S{i}", area_id=area_id))["id"] for i in range(3)]

    await update_slice(ctx, ids, status="dropped")

    for sid in ids:
        assert "dropped" in await get_slice(ctx, sid, with_activity=True)
