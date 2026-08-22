import types

import pytest

from tuckit.core.mcp.server import get_project_state
from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tokens import generate_token


def make_ctx(raw_token: str):
    """Build a fake MCP Context exposing request headers, matching the real
    ctx.request_context.request.headers accessor the tool relies on."""
    request = types.SimpleNamespace(headers={"authorization": f"Bearer {raw_token}"})
    request_context = types.SimpleNamespace(request=request)
    return types.SimpleNamespace(request_context=request_context)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_project_state_tool_returns_state():
    org = await _make_org()
    _, raw = await _make_token(org)
    result = await get_project_state(make_ctx(raw))
    assert result["org"]["name"] == "Acme"
    assert [a["shipped"][0]["title"] for a in result["areas"]] == ["Auth"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_project_state_tool_rejects_bad_token():
    from tuckit.core.services.exceptions import NotFound

    await _make_org()
    with pytest.raises(NotFound):
        await get_project_state(make_ctx("bogus-token"))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_project_state_includes_caller_identity_legacy_token():
    org = await _make_org()
    _, raw = await _make_token(org)  # legacy ApiToken -> no user
    result = await get_project_state(make_ctx(raw))
    assert result["caller"]["org_slug"] == "acme"
    assert result["caller"]["user_email"] is None


# --- async helpers (ORM access wrapped for the async test) ---
from asgiref.sync import sync_to_async  # noqa: E402


@sync_to_async
def _make_org():
    org = Org.objects.create(name="Acme", slug="acme", description="demo")
    area = create_area(org, "Backend")
    create_slice(area.org, area=area, title="Auth", status="shipped")
    return org


@sync_to_async
def _make_token(org):
    return generate_token(org, "test")


# --- the shape of the pile, not just its contents (TP-253) ----------------
#
# get_project_state is the FIRST call of every session, and it used to report
# `counts: {"shipped": N}` and an uncapped list of every open slice. So the one
# tool built to orient an agent grew without limit as the board filled, while
# the two numbers that would have said the board was filling -- how many are
# open, and what share of captures gets dropped -- were not in it at all.


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_counts_report_open_and_dropped_not_only_shipped():
    org = await _make_org()
    _, raw = await _make_token(org)
    await _add_slices(org, open_n=3, dropped_n=2)

    area = (await get_project_state(make_ctx(raw)))["areas"][0]

    assert area["counts"] == {"open": 3, "shipped": 1, "dropped": 2}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_drop_ratio_is_the_denominator_the_review_gate_never_had():
    """1 shipped + 3 open + 6 dropped = 60% of everything captured turned out
    not to be work. That is the number "will anyone actually do it later?" is
    a guess about, and it was unreachable from MCP."""
    org = await _make_org()
    _, raw = await _make_token(org)
    await _add_slices(org, open_n=3, dropped_n=6)

    totals = (await get_project_state(make_ctx(raw)))["totals"]

    assert totals["open"] == 3 and totals["shipped"] == 1 and totals["dropped"] == 6
    assert totals["drop_ratio"] == 0.6


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_totals_split_human_from_agent_authorship():
    """create_slice stamps source="agent" on every MCP write, so who fills the
    board has been recorded since the beginning and read by nobody."""
    org = await _make_org()
    _, raw = await _make_token(org)
    await _add_slices(org, open_n=4, source="agent")

    assert (await get_project_state(make_ctx(raw)))["totals"]["by_source"] == {
        "human": 1, "agent": 4,
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_roadmap_is_capped_and_says_how_much_it_left_out():
    """A silent truncation reads as "that was all of it" -- worse than the wall
    it replaces. counts.open stays the real number."""
    from tuckit.core.services.state import ROADMAP_LIMIT

    org = await _make_org()
    _, raw = await _make_token(org)
    await _add_slices(org, open_n=ROADMAP_LIMIT + 7)

    area = (await get_project_state(make_ctx(raw)))["areas"][0]

    assert len(area["roadmap"]) == ROADMAP_LIMIT
    assert area["roadmap_omitted"] == 7
    assert area["counts"]["open"] == ROADMAP_LIMIT + 7


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_board_under_the_cap_omits_nothing():
    org = await _make_org()
    _, raw = await _make_token(org)
    await _add_slices(org, open_n=2)

    area = (await get_project_state(make_ctx(raw)))["areas"][0]

    assert len(area["roadmap"]) == 2 and area["roadmap_omitted"] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_inbox_reports_how_long_its_oldest_capture_has_waited():
    """"34 waiting" is a number you look past; "the oldest has sat 40 days" is
    one that decides something."""
    org = await _make_org()
    _, raw = await _make_token(org)
    await _age_an_inbox_capture(org, days=40)

    inbox = (await get_project_state(make_ctx(raw)))["inbox"]

    assert inbox["open_count"] == 1
    assert inbox["oldest_idle_days"] == 40


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_empty_inbox_reports_no_age_rather_than_zero():
    """Zero would read as "something is waiting, filed today"."""
    org = await _make_org()
    _, raw = await _make_token(org)

    assert (await get_project_state(make_ctx(raw)))["inbox"]["oldest_idle_days"] is None


@sync_to_async
def _add_slices(org, *, open_n=0, dropped_n=0, source="human"):
    from tuckit.core.models import Area

    area = Area.objects.filter(org=org).first()
    for i in range(open_n):
        create_slice(org, area=area, title=f"Open {i}", source=source)
    for i in range(dropped_n):
        create_slice(org, area=area, title=f"Dropped {i}", status="dropped", source=source)


@sync_to_async
def _age_an_inbox_capture(org, *, days):
    from datetime import timedelta

    from django.utils import timezone

    from tuckit.core.models import Slice

    s = create_slice(org, area=None, title="Unfiled")
    # auto_now/auto_now_add ignore assignment; move the columns with an UPDATE.
    then = timezone.now() - timedelta(days=days)
    Slice.objects.filter(id=s.id).update(created_at=then, updated_at=then)


# --- priority: the criteria, and a cap that means something (TP-178) ---------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_project_state_carries_the_priority_policy():
    """An agent that cannot read the policy has nothing to classify against,
    and falls back to its own priors -- which know general urgency and not this
    company's."""
    org = await _make_org()
    _, raw = await _make_token(org)
    await _set_policy(org, "1 = money in hand this week. 2 = a date promised outside.")

    state = await get_project_state(make_ctx(raw))

    assert "money in hand" in state["org"]["priority_policy"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unwritten_policy_is_an_empty_string_not_an_error():
    """Empty is the normal state of every org before anyone writes one."""
    org = await _make_org()
    _, raw = await _make_token(org)

    assert (await get_project_state(make_ctx(raw)))["org"]["priority_policy"] == ""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_capped_roadmap_keeps_the_highest_priorities():
    """TP-253 capped this list before anything could rank it, so the 20 it kept
    were whichever happened to sit highest in the manual order. This is the
    line that makes the cap mean something.

    The ranked slice is the LAST one created, so it sits at the bottom of rank
    order and outside the cap entirely. If the sort did not happen before the
    cut it would not merely be in the wrong position -- it would be missing.
    """
    from tuckit.core.services.state import ROADMAP_LIMIT

    org = await _make_org()
    _, raw = await _make_token(org)
    await _add_slices(org, open_n=ROADMAP_LIMIT + 5)
    await _rank_one_slice_last_created(org, priority=1)

    area = (await get_project_state(make_ctx(raw)))["areas"][0]

    assert area["roadmap"][0]["title"] == "Open %d" % (ROADMAP_LIMIT + 4)
    assert area["roadmap_omitted"] == 5


@sync_to_async
def _set_policy(org, text):
    org.priority_policy = text
    org.save(update_fields=["priority_policy", "updated_at"])


@sync_to_async
def _rank_one_slice_last_created(org, *, priority):
    from tuckit.core.models import Slice

    last = Slice.objects.filter(org=org).order_by("-id").first()
    Slice.objects.filter(id=last.id).update(priority=priority)
