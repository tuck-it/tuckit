import pytest
from datetime import timedelta
from django.utils import timezone

from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import add_bites, create_bite, update_bite
from tuckit.core.services.slices import create_slice
from tuckit.core.services.state import (
    AREA_STATUS_KEYS,
    area_board_view,
    cap_shipped,
    home_state,
    roadmap_board_view,
    roadmap_state,
    STALE_DAYS,
    get_project_state,
    mark_home_seen,
    render_slice_markdown,
    since_last_visit,
    your_turn,
)


@pytest.fixture
def product_org(db):
    return Org.objects.create(name="MyProduct", slug="myproduct", description="A demo product")


@pytest.fixture
def area(org):
    return create_area(org, "Backend")


@pytest.mark.django_db
def test_project_state_buckets_by_status(product_org):
    product_org.description = "A demo product"
    product_org.save(update_fields=["description", "updated_at"])
    area = create_area(product_org, "Backend")
    create_slice(area.org, area=area, title="Auth", status="shipped")
    create_slice(area.org, area=area, title="Payments", status="open")
    create_slice(area.org, area=area, title="Notifications", status="open")

    state = get_project_state(product_org)
    assert state["org"]["description"] == "A demo product"
    a = state["areas"][0]
    assert [s["title"] for s in a["shipped"]] == ["Auth"]
    assert {s["title"] for s in a["roadmap"]} == {"Payments", "Notifications"}
    assert a["counts"]["shipped"] == 1


@pytest.mark.django_db
def test_project_state_inbox_counts_area_less_slices(product_org):
    """The `inbox` aggregate reads area-less Slices, not Tickets. This is the
    only place get_project_state reports untriaged work, and it is how an agent
    that calls one tool at the start of a session learns the Inbox is not
    empty — before this it counted a table nothing writes to any more."""
    area = create_area(product_org, "Backend")
    create_slice(product_org, area=area, title="filed work")
    create_slice(product_org, title="unfiled capture")
    create_slice(product_org, title="another capture")

    inbox = get_project_state(product_org)["inbox"]

    assert inbox["open_count"] == 2
    assert {row["title"] for row in inbox["recent"]} == {"unfiled capture", "another capture"}


@pytest.mark.django_db
def test_project_state_inbox_ignores_shipped_and_dropped_captures(product_org):
    """inbox_slices() is status='open' only — a capture someone dropped without
    filing is a closed decision, not a thing still waiting on you."""
    create_slice(product_org, title="still waiting")
    create_slice(product_org, title="dropped capture", status="dropped")

    inbox = get_project_state(product_org)["inbox"]

    assert inbox["open_count"] == 1
    assert [row["title"] for row in inbox["recent"]] == ["still waiting"]


@pytest.mark.django_db
def test_project_state_can_scope_to_one_area(product_org):
    a1 = create_area(product_org, "Backend")
    create_area(product_org, "Frontend")
    create_slice(a1.org, area=a1, title="Auth", status="shipped")
    state = get_project_state(product_org, area=a1)
    assert len(state["areas"]) == 1
    assert state["areas"][0]["slug"] == a1.slug


def _migrated_bite(slice_, title, **kw):
    """A bite in the shape migration 0045 left behind.

    0045 reparented every pre-release step onto its slice while leaving
    Bite.plan populated, and the renderer's old `plan__isnull=True` filter
    would have hidden all of them. 0050 dropped the column, so the two shapes
    are now literally the same row — kept as a named builder because the
    callers below are about that distinction and would otherwise read as
    duplicate assertions."""
    return create_bite(slice_, title, **kw)


@pytest.mark.django_db
def test_render_slice_markdown_includes_spec_and_bites(product_org):
    area = create_area(product_org, "Backend")
    s = create_slice(area.org, area=area, title="Auth", spec="Support OAuth login.", status="open", tags=["feature"])
    create_bite(s, "JWT", status="done")
    create_bite(s, "Social login", status="todo")

    md = render_slice_markdown(s)
    assert "# Auth" in md
    assert "Support OAuth login." in md
    assert "- [x] JWT" in md
    assert "- [ ] Social login" in md
    assert "#feature" in md


@pytest.mark.django_db
def test_render_slice_markdown_includes_bite_body(product_org):
    area = create_area(product_org, "Backend")
    s = create_slice(area.org, area=area, title="Auth")
    create_bite(s, "JWT", body="use RS256 keys")
    md = render_slice_markdown(s)
    assert "- [ ] JWT" in md
    assert "use RS256 keys" in md


@pytest.mark.django_db
def test_render_slice_markdown_emits_the_slices_own_constraints(product_org):
    """Constraints is a Slice field now (Task 10 gave it a first-class editor).
    Promoting it is only worth anything if a later agent session can READ it:
    get_slice() is that path, so the section has to be here, after the spec and
    before the steps a caller is about to work through."""
    area = create_area(product_org, "Backend")
    s = create_slice(
        area.org, area=area, title="Auth", spec="Support OAuth login.",
        constraints="hx-swap을 명시할 것 — 아니면 200이 조용히 버려진다.",
    )
    create_bite(s, "JWT")

    md = render_slice_markdown(s)

    assert "## Constraints" in md
    assert "hx-swap을 명시할 것" in md
    assert md.index("Support OAuth login.") < md.index("## Constraints") < md.index("## Steps")
    assert "- [ ] JWT" in md


@pytest.mark.django_db
def test_render_slice_markdown_omits_the_constraints_header_when_empty(product_org):
    """An empty section would teach every agent that the field is decoration."""
    area = create_area(product_org, "Backend")
    s = create_slice(area.org, area=area, title="Auth", spec="design")

    assert "## Constraints" not in render_slice_markdown(s)


@pytest.mark.django_db
def test_render_slice_markdown_shows_plan_less_bites_under_a_steps_header(product_org):
    """Bites created via add_bites() (Task 5) have no plan to nest under, so
    they must still surface somewhere in get_slice() output — otherwise an
    agent's own add_bites() call would vanish from its next get_slice()."""
    area = create_area(product_org, "Backend")
    s = create_slice(area.org, area=area, title="Auth", spec="design")
    create_bite(s, "JWT", status="done")
    create_bite(s, "Social login", body="use RS256 keys")

    md = render_slice_markdown(s)

    assert "## Steps" in md
    assert "- [x] JWT" in md
    assert "- [ ] Social login" in md
    assert "use RS256 keys" in md


@pytest.mark.django_db
def test_render_slice_markdown_omits_the_steps_header_when_there_are_no_bites(product_org):
    area = create_area(product_org, "Backend")
    s = create_slice(area.org, area=area, title="Auth", spec="design")

    assert "## Steps" not in render_slice_markdown(s)


@pytest.mark.django_db
def test_render_slice_markdown_lists_migrated_and_new_bites_in_one_checklist(product_org):
    """The whole slice, one list. A slice can hold both a bite migration 0045
    left with Bite.plan populated and one added after this release with no
    plan at all; get_slice() must show both. This is the case the old
    `plan__isnull=True` filter got wrong — with the Plan sections deleted it
    would have silently dropped every pre-release step.

    There must be no per-plan heading: `## Plan` reappearing here would put the
    retired layer back in front of the one reader who cannot see anything else.
    """
    area = create_area(product_org, "Backend")
    s = create_slice(area.org, area=area, title="Auth", spec="design")
    _migrated_bite(s, "Migrated bite")
    create_bite(s, "New bite")

    md = render_slice_markdown(s)

    assert md.count("## Steps") == 1
    assert "- [ ] Migrated bite" in md
    assert "- [ ] New bite" in md
    assert "## Plan" not in md


@pytest.mark.django_db
def test_someday_tag_no_longer_buckets_separately(product_org):
    """someday is a plain tag again — the special-casing that pulled
    #someday slices into their own bucket is gone (state.py _area_state)."""
    area = create_area(product_org, "Backend")
    create_slice(area.org, area=area, title="Planned someday", status="open", tags=["someday"])
    create_slice(area.org, area=area, title="Plain planned", status="open")
    state = get_project_state(product_org)
    a = state["areas"][0]
    assert "someday" not in a
    assert {s["title"] for s in a["roadmap"]} == {"Planned someday", "Plain planned"}


@pytest.mark.django_db
def test_home_state_keeps_every_in_progress_slice_visible():
    """The old Home silently dropped a building slice from its Focus column
    once it also landed in the attention list, and dropped `someday`-tagged
    ones outright. A slice whose stage is executing but which is missing from
    the in_progress list is the bug this replaces — there is no hidden filter
    (tag or otherwise) on top of the stage check."""
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")

    def executing(title, **kw):
        s = create_slice(a.org, area=a, title=title, spec="design", **kw)
        create_bite(s, "step", status="doing")
        return s

    stalled = executing("stalled")
    executing("parked", tags=["someday"])
    executing("fresh")
    Slice.objects.filter(pk=stalled.pk).update(
        updated_at=timezone.now() - timedelta(days=30)
    )

    titles = [s.title for s in home_state(org)["in_progress"]]
    assert set(titles) == {"stalled", "parked", "fresh"}
    assert titles[0] == "stalled", "stalled sorts first — sort key, not filter"


@pytest.mark.django_db
def test_home_state_counts_backlog_without_listing_it():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    create_slice(a.org, area=a, title="queued", status="open")
    create_slice(a.org, area=a, title="someday one", status="open", tags=["someday"])
    st = home_state(org)
    assert st["open_ct"] == 2
    assert "open" not in st, "the backlog is Board's job — Home links to it"


@pytest.mark.django_db
def test_roadmap_state_buckets_by_status():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    create_slice(a.org, area=a, title="open one", status="open")
    create_slice(a.org, area=a, title="shipped one", status="shipped")
    create_slice(a.org, area=a, title="dropped one", status="dropped")
    rs = roadmap_state(org)
    assert [s.title for s in rs["open"]] == ["open one"]
    assert [s.title for s in rs["shipped"]] == ["shipped one"]
    assert "dropped" not in rs                                   # dropped never bucketed
    assert "idea" not in rs                                      # the 'idea' status is retired


@pytest.mark.django_db
def test_roadmap_sorts_by_area_name():
    org = Org.objects.create(name="Acme", slug="acme")
    zeta = create_area(org, "Zeta")
    alpha = create_area(org, "Alpha")
    # Created Zeta-first, but must come back Alpha-first (sort key is
    # (area name, rank)). Guards against the sort key being dropped/reversed.
    create_slice(zeta.org, area=zeta, title="z open", status="open")
    create_slice(alpha.org, area=alpha, title="a open", status="open")
    assert [s.title for s in roadmap_state(org)["open"]] == ["a open", "z open"]


@pytest.mark.django_db
def test_roadmap_state_excludes_inbox_slices():
    """Regression (Task 6 fix round 1): an area-less (Inbox) slice used to blow
    up bucket()'s `s.area.name` sort key with an AttributeError. filed_slices()
    must drop it before the sort ever sees it — the Inbox has its own screen,
    not this org-wide flat list."""
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    filed = create_slice(a.org, area=a, title="filed", status="open")
    create_slice(org, title="unfiled capture", status="open")   # no area
    rs = roadmap_state(org)   # must not raise
    assert [s.title for s in rs["open"]] == ["filed"]
    assert filed.id


@pytest.mark.django_db
def test_cap_shipped_count_mode(product_org):
    product_org.shipped_board_mode = "count"
    product_org.shipped_board_limit = 2
    a = create_area(product_org, "A")
    for i in range(5):
        create_slice(a.org, area=a, title=f"s{i}", status="shipped")
    shipped = roadmap_state(product_org)["shipped"]
    visible, total = cap_shipped(product_org, shipped)
    assert total == 5
    assert len(visible) == 2


@pytest.mark.django_db
def test_cap_shipped_days_mode_excludes_old(product_org):
    product_org.shipped_board_mode = "days"
    product_org.shipped_board_limit = 30
    a = create_area(product_org, "A")
    recent = create_slice(a.org, area=a, title="recent", status="shipped")
    old = create_slice(a.org, area=a, title="old", status="shipped")
    old.completed_at = timezone.now() - timedelta(days=90)
    old.save(update_fields=["completed_at"])
    shipped = roadmap_state(product_org)["shipped"]
    visible, total = cap_shipped(product_org, shipped)
    assert total == 2
    titles = {s.title for s in visible}
    assert "recent" in titles and "old" not in titles


@pytest.mark.django_db
def test_shipped_sorted_newest_first(product_org):
    a = create_area(product_org, "A")
    first = create_slice(a.org, area=a, title="first", status="shipped")
    second = create_slice(a.org, area=a, title="second", status="shipped")
    first.completed_at = timezone.now() - timedelta(days=5)
    first.save(update_fields=["completed_at"])
    shipped = roadmap_state(product_org)["shipped"]
    assert [s.title for s in shipped][:2] == ["second", "first"]


@pytest.mark.django_db
def test_roadmap_board_view_reports_overflow(product_org):
    product_org.shipped_board_mode = "count"
    product_org.shipped_board_limit = 1
    a = create_area(product_org, "A")
    create_slice(a.org, area=a, title="s1", status="shipped")
    create_slice(a.org, area=a, title="s2", status="shipped")
    view = roadmap_board_view(product_org)
    assert view["shipped_total"] == 2
    assert view["shipped_hidden"] == 1
    shipped_group = dict(view["groups"])["shipped"]
    assert len(shipped_group) == 1


@pytest.mark.django_db
def test_roadmap_board_view_buckets_by_stage(product_org):
    from tuckit.core.services.bites import create_bite

    a = create_area(product_org, "Backend")
    create_slice(a.org, area=a, title="no spec")                                   # needs_design
    create_slice(a.org, area=a, title="spec only", spec="s")                      # needs_steps
    ex = create_slice(a.org, area=a, title="in progress", spec="s")
    create_bite(ex, "b", status="doing")                        # executing
    rts = create_slice(a.org, area=a, title="all done", spec="s")
    create_bite(rts, "b", status="done")                        # ready_to_ship
    create_slice(a.org, area=a, title="done", status="shipped")                   # shipped
    create_slice(a.org, area=a, title="abandoned", status="dropped")              # dropped (counted, not shown)

    view = roadmap_board_view(product_org)
    groups = dict(view["groups"])

    assert [k for k, _ in view["groups"]] == [
        "needs_design", "needs_steps", "executing", "ready_to_ship", "shipped",
    ]
    assert [s.title for s in groups["needs_design"]] == ["no spec"]
    assert {s.title for s in groups["needs_steps"]} == {"spec only"}
    assert [s.title for s in groups["executing"]] == ["in progress"]
    assert [s.title for s in groups["ready_to_ship"]] == ["all done"]
    assert [s.title for s in groups["shipped"]] == ["done"]
    assert view["dropped_count"] == 1


@pytest.mark.django_db
def test_roadmap_board_view_attaches_raw_stage_to_each_slice(product_org):
    """A spec with no bites lands in needs_steps.

    This used to assert the same for a slice carrying an empty Plan, to pin
    down that the Plan layer did not factor into stage (Task 4). That case is
    unbuildable now — 0050 dropped the table — so what is left is the rule
    itself: stage reads bites, and nothing else."""
    a = create_area(product_org, "Backend")
    create_slice(a.org, area=a, title="spec only", spec="s")
    create_slice(a.org, area=a, title="spec only too", spec="s")

    groups = dict(roadmap_board_view(product_org)["groups"])
    by_title = {s.title: s.stage for s in groups["needs_steps"]}
    assert by_title == {"spec only": "needs_steps", "spec only too": "needs_steps"}


@pytest.mark.django_db
def test_roadmap_board_view_excludes_inbox_slices(product_org):
    """Regression (Task 6 fix round 1): roadmap_board_view() queried
    Slice.objects directly with no area filter, so an unfiled capture flooded
    the org Board's needs_design column. The Inbox has its own screen."""
    a = create_area(product_org, "Backend")
    create_slice(a.org, area=a, title="filed", spec="s")           # needs_steps
    create_slice(product_org, title="unfiled capture")             # Inbox — no area

    groups = dict(roadmap_board_view(product_org)["groups"])
    titles = {s.title for col in groups.values() for s in col}
    assert titles == {"filed"}


def test_snapshot_today_still_accrues_history(product_org):
    """Nothing renders these numbers now. The row is still written so the daily
    history keeps accruing for a future metrics screen — a gap no backfill can
    fill."""
    from tuckit.core.services.state import snapshot_today
    from tuckit.core.models import OrgStatSnapshot

    a = create_area(product_org, "A")
    s = create_slice(a.org, area=a, title="b", spec="design")
    create_bite(s, "step", status="doing")
    snapshot_today(product_org, home_state(product_org), 0)
    snapshot_today(product_org, home_state(product_org), 0)

    assert OrgStatSnapshot.objects.filter(org=product_org).count() == 1
    assert OrgStatSnapshot.objects.get(org=product_org).building_ct == 1


@pytest.mark.django_db
def test_project_state_names_the_org_not_a_product(org):
    org.description = "our company"
    org.save(update_fields=["description", "updated_at"])
    state = get_project_state(org)
    assert "product" not in state
    # priority_policy is unwritten here, which is every org's starting state.
    # That it CARRIES a written one is pinned in test_mcp_tools_state.py, where
    # the agent-facing contract lives.
    assert state["org"] == {
        "name": org.name, "description": "our company", "priority_policy": "",
    }


@pytest.mark.django_db
def test_slice_markdown_carries_no_ticket_provenance_line():
    """The `From: ACM-n` line is gone. It pointed at Tickets, and 0045 already
    appended every captured body into the slice's own spec — so the line named
    a row an agent has no tool to read and no reason to. The folded slice below
    is built in exactly the shape 0045 left: spec carrying the capture, no
    provenance line anywhere."""
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.state import render_slice_markdown

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    folded = create_slice(org, area=area, title="Origin",
                          spec="### original capture (Origin)\n\nthe captured body")
    direct = create_slice(org, area=area, title="Direct")

    assert "From:" not in render_slice_markdown(folded)
    assert "From:" not in render_slice_markdown(direct)


@pytest.mark.django_db
def test_slice_markdown_reports_the_stage_under_status():
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.state import render_slice_markdown

    org = Org.objects.create(name="Acme", slug="acme")
    s = create_slice(org, area=create_area(org, "Backend"), title="Blank")

    lines = render_slice_markdown(s).splitlines()
    assert "Stage: needs_design" in lines
    # directly under Status, where the actionable fact belongs
    status_line = next(l for l in lines if l.startswith("Status:"))
    assert lines.index("Stage: needs_design") == lines.index(status_line) + 1


@pytest.mark.django_db
def test_shipped_slice_markdown_does_not_ask_for_a_design_doc():
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.state import render_slice_markdown

    org = Org.objects.create(name="Acme", slug="acme")
    s = create_slice(org, area=create_area(org, "Backend"), title="Done", status="shipped")

    md = render_slice_markdown(s)
    assert "Stage: shipped" in md
    assert "needs_design" not in md


@pytest.mark.django_db
def test_area_board_view_excludes_dropped_and_counts_it(product_org):
    a = create_area(product_org, "A")
    create_slice(a.org, area=a, title="live one", status="open")
    create_slice(a.org, area=a, title="gone one", status="dropped")
    view = area_board_view(a)
    assert "dropped" not in dict(view["groups"])
    titles = {s.title for _, group in view["groups"] for s in group}
    assert titles == {"live one"}
    assert view["dropped_count"] == 1


@pytest.mark.django_db
def test_area_board_view_caps_shipped_by_recency_not_rank(product_org):
    """cap_shipped's count mode assumes a recency-sorted list, but
    grouped_slices orders by rank. Without an explicit sort the board keeps
    the top-ranked shipped slice instead of the most recently completed one."""
    product_org.shipped_board_mode = "count"
    product_org.shipped_board_limit = 1
    product_org.save(update_fields=["shipped_board_mode", "shipped_board_limit", "updated_at"])
    a = create_area(product_org, "A")
    first = create_slice(a.org, area=a, title="older", status="shipped")
    create_slice(a.org, area=a, title="newer", status="shipped")
    first.completed_at = timezone.now() - timedelta(days=5)
    first.save(update_fields=["completed_at"])
    view = area_board_view(a)
    shipped = dict(view["groups"])["shipped"]
    assert [s.title for s in shipped] == ["newer"]
    assert view["shipped_total"] == 2
    assert view["shipped_hidden"] == 1


@pytest.mark.django_db
def test_area_board_view_has_any_slice_counts_capped_and_dropped(product_org):
    """A slice that exists but is not rendered in a column still means the
    area is not empty — otherwise the board shows "No slices yet." next to a
    "View all shipped" or "Dropped" link, which contradicts itself."""
    product_org.shipped_board_mode = "count"
    product_org.shipped_board_limit = 0
    product_org.save(update_fields=["shipped_board_mode", "shipped_board_limit", "updated_at"])
    a = create_area(product_org, "A")
    create_slice(a.org, area=a, title="capped out", status="shipped")
    assert area_board_view(a)["has_any_slice"] is True

    b = create_area(product_org, "B")
    create_slice(b.org, area=b, title="dropped only", status="dropped")
    assert area_board_view(b)["has_any_slice"] is True

    c = create_area(product_org, "C")
    assert area_board_view(c)["has_any_slice"] is False


@pytest.mark.django_db
def test_area_status_keys_include_dropped(product_org):
    assert AREA_STATUS_KEYS == {"open", "shipped", "dropped"}


@pytest.mark.django_db
def test_area_board_view_buckets_by_stage_and_scopes_to_area(product_org):
    from tuckit.core.services.bites import create_bite

    a = create_area(product_org, "A")
    other = create_area(product_org, "B")
    create_slice(a.org, area=a, title="no spec")                                  # needs_design
    rts = create_slice(a.org, area=a, title="all done", spec="s")
    create_bite(rts, "b", status="done")                        # ready_to_ship
    create_slice(a.org, area=a, title="gone", status="dropped")                   # dropped
    create_slice(other.org, area=other, title="elsewhere")                            # different area

    view = area_board_view(a)
    groups = dict(view["groups"])
    assert [k for k, _ in view["groups"]] == [
        "needs_design", "needs_steps", "executing", "ready_to_ship", "shipped",
    ]
    assert [s.title for s in groups["needs_design"]] == ["no spec"]
    assert [s.title for s in groups["ready_to_ship"]] == ["all done"]
    assert "dropped" not in groups
    assert view["dropped_count"] == 1
    all_titles = {s.title for _, g in view["groups"] for s in g}
    assert "elsewhere" not in all_titles      # scoped to area A


@pytest.mark.django_db
def test_your_turn_includes_specless_open_slice():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="started but undesigned", status="open")  # spec=""
    items = your_turn(org)
    hit = [it for it in items if it.get("slice") and it["slice"].id == s.id]
    assert hit, "an open slice with no spec is blocked on a human"
    assert hit[0]["action"] == "write the spec"


@pytest.mark.django_db
def test_your_turn_includes_slice_whose_bites_are_all_done():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="finished work", status="open", spec="designed")
    create_bite(s, "one", status="done")
    items = your_turn(org)
    hit = [it for it in items if it.get("slice") and it["slice"].id == s.id]
    assert hit
    assert hit[0]["action"] == "verify and ship"


@pytest.mark.django_db
def test_your_turn_excludes_stages_an_agent_can_do():
    """needs_steps is agent work — add_bites exists for exactly that. Listing
    it here would nag daily.

    The companion case, a slice carrying an empty Plan, is gone with the table
    (0050). It existed to pin down that the Plan layer did not factor into
    stage; there is no Plan layer left to factor."""
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    bare = create_slice(a.org, area=a, title="designed, no bites", status="open", spec="designed")

    ids = {it["slice"].id for it in your_turn(org) if it.get("slice")}
    assert bare.id not in ids


@pytest.mark.django_db
def test_your_turn_excludes_inbox_slices():
    """Regression (Task 6 fix round 1): an unfiled capture (area IS NULL, spec
    empty) used to surface here as 'write the spec'. It isn't yet — the actual
    next step is triaging it (giving it an area), which is the Inbox screen's
    job, not this band's."""
    org = Org.objects.create(name="Acme", slug="acme")
    create_slice(org, title="unfiled capture", status="open")   # no area, no spec
    ids = {it["slice"].id for it in your_turn(org) if it.get("slice")}
    assert ids == set()


@pytest.mark.django_db
def test_your_turn_aggregates_unfiled_captures_into_one_row():
    """Unfiled (area-less) slices are the Inbox now (Task 6/7) — there is no
    separate Ticket count to aggregate any more. The same "one row, not N"
    contract applies: the Inbox already lists captures individually."""
    org = Org.objects.create(name="Acme", slug="acme")
    for i in range(3):
        create_slice(org, title=f"capture {i}", status="open")   # no area
    rows = [it for it in your_turn(org) if "inbox" in it]
    assert len(rows) == 1, "the Inbox already lists captures individually"
    assert rows[0]["inbox"] == 3
    assert rows[0]["action"] == "3 in Inbox"
    assert "inbox" in your_turn(org)[-1], "the aggregate row sorts last"


@pytest.mark.django_db
def test_your_turn_sorts_longest_blocked_first():
    """Staleness is the sort key, never an inclusion rule — a 'stale' section
    would be a guilt list that only ever grows."""
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    recent = create_slice(a.org, area=a, title="recent", status="open")
    old = create_slice(a.org, area=a, title="old", status="open")
    Slice.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=30))
    titles = [it["slice"].title for it in your_turn(org) if it.get("slice")]
    assert titles == ["old", "recent"]
    assert recent.id  # referenced so the fixture reads as intentional


@pytest.mark.django_db
def test_your_turn_is_empty_when_nothing_is_blocked():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="moving along", status="open", spec="designed")
    create_bite(s, "in flight", status="todo")
    assert your_turn(org) == []


def _member(org):
    from tuckit.core.models import OrgMember, User
    user = User.objects.create_user(email=f"m{org.pk}@example.com", password="x")
    return OrgMember.objects.create(user=user, org=org, role="owner")


@pytest.mark.django_db
def test_since_last_visit_badges_nothing_on_a_first_visit():
    from tuckit.core.services.activity import record_activity

    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="work", status="open")
    record_activity(org, source="agent", verb="created", target=s)

    out = since_last_visit(org, _member(org))
    assert out["new_count"] == 0
    assert all(not e.is_new for e in out["events"])
    assert len(out["events"]) >= 1, "the log still renders — only the badge is empty"


@pytest.mark.django_db
def test_since_last_visit_counts_only_agent_events_as_new():
    """In a solo org every 'human' event is the viewer's own. Badging your own
    work as news is noise, so it renders for context but never counts."""
    from tuckit.core.services.activity import record_activity

    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="work", status="open")
    m = _member(org)
    mark_home_seen(m)

    record_activity(org, source="agent", verb="shipped", target=s)
    record_activity(org, source="human", verb="noted", target=s, body="mine")

    out = since_last_visit(org, m)
    assert out["new_count"] == 1
    assert sum(1 for e in out["events"] if e.is_new) == 2, "both are new..."
    assert [e.source for e in out["events"] if e.is_new].count("human") == 1, \
        "...but the human one is not counted"


@pytest.mark.django_db
def test_mark_home_seen_advances_the_watermark():
    org = Org.objects.create(name="Acme", slug="acme")
    m = _member(org)
    assert m.home_seen_at is None

    mark_home_seen(m)
    m.refresh_from_db()
    first = m.home_seen_at
    assert first is not None

    mark_home_seen(m)
    m.refresh_from_db()
    assert m.home_seen_at > first


@pytest.mark.django_db
def test_since_last_visit_is_capped_and_newest_first():
    from tuckit.core.services.activity import record_activity

    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="work", status="open")
    for i in range(15):
        record_activity(org, source="agent", verb="noted", target=s, body=f"n{i}")

    out = since_last_visit(org, _member(org), limit=10)
    assert len(out["events"]) == 10
    stamps = [e.created_at for e in out["events"]]
    assert stamps == sorted(stamps, reverse=True)


@pytest.mark.django_db
def test_in_progress_band_follows_stage_not_status(org, area):
    """status를 손대지 않아도 bite가 진행 중이면 in progress에 나타난다.
    예전에는 status='building'을 사람이 켜야 했고, 아무도 안 켜서 밴드가
    상시 비어 있었다 (A0)."""
    s = create_slice(area.org, area=area, title="spec 있는 일", spec="왜 하는지", status="open")
    add_bites(s, [{"title": "첫 단계"}, {"title": "둘째 단계"}])
    update_bite(s.bites.first(), status="done")

    state = home_state(area.org)

    assert [x.title for x in state["in_progress"]] == ["spec 있는 일"]
    s.refresh_from_db()
    assert s.status == "open"  # status는 그대로다


@pytest.mark.django_db
def test_your_turn_lists_specless_open_slices(org, area):
    """spec이 비면 사람이 써야 한다 — 그게 '내 차례'다. 예전에는
    status='building'인 것만 봐서 이 밴드도 비어 있었다."""
    create_slice(area.org, area=area, title="설계 필요", spec="", status="open")
    create_slice(area.org, area=area, title="설계 끝남", spec="왜 하는지", status="open")

    rows = [r for r in your_turn(area.org) if "slice" in r]

    assert [(r["slice"].title, r["action"]) for r in rows] == [
        ("설계 필요", "write the spec"),
    ]


@pytest.mark.django_db
def test_shipped_slices_never_reach_your_turn(org, area):
    """끝난 일은 내 차례가 아니다."""
    create_slice(area.org, area=area, title="이미 나감", spec="", status="shipped")

    assert [r for r in your_turn(area.org) if "slice" in r] == []


# ---- the decision record over MCP ----------------------------------------

def _with_record(org, area, nodes):
    s = create_slice(org, area=area, title="Canvas", spec="designed")
    s.decision_tree = {"nodes": nodes}
    s.save(update_fields=["decision_tree"])
    return s


@pytest.mark.django_db
def test_the_decision_record_reaches_an_agent_with_node_ids(org, area):
    # The ids are the load-bearing part: without them a later session cannot
    # send parent=<the winner>, and the propose guard can only ever reject it.
    s = _with_record(org, area, [
        {"id": "q1", "parent": None, "kind": "question",
         "title": "Where do we notify?", "chosen": "o1", "at": 1},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "A note", "at": 1},
        {"id": "o2", "parent": "q1", "kind": "option", "title": "Email", "at": 1},
    ])

    out = render_slice_markdown(s)

    assert "## Decisions" in out
    assert "[q1]" in out and "[o1]" in out and "[o2]" in out
    assert "Where do we notify?" in out


@pytest.mark.django_db
def test_each_question_reports_which_state_it_is_in(org, area):
    s = _with_record(org, area, [
        {"id": "r", "parent": None, "kind": "note", "title": "Problem", "at": 1},
        {"id": "q1", "parent": "r", "kind": "question", "title": "First", "at": 1},
        {"id": "q2", "parent": "r", "kind": "question", "title": "Second", "at": 2},
    ])

    out = render_slice_markdown(s)

    assert "First -- passed" in out
    assert "Second -- waiting" in out


@pytest.mark.django_db
def test_a_locked_question_says_so_so_an_agent_does_not_offer_to_change_it(org, area):
    s = _with_record(org, area, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Q",
         "chosen": "o1", "at": 1},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "A", "at": 1},
        {"id": "d1", "parent": "o1", "kind": "note", "title": "Because", "at": 2},
    ])

    assert "locked" in render_slice_markdown(s)


@pytest.mark.django_db
def test_bodies_are_left_out_so_a_big_canvas_does_not_swamp_the_response(org, area):
    s = _with_record(org, area, [
        {"id": "n1", "parent": None, "kind": "note", "title": "Head",
         "body": "SHOULD-NOT-APPEAR " * 40, "at": 1},
    ])

    assert "SHOULD-NOT-APPEAR" not in render_slice_markdown(s)


@pytest.mark.django_db
def test_a_slice_with_no_record_grows_no_section(org, area):
    s = create_slice(org, area=area, title="Plain", spec="designed")

    assert "## Decisions" not in render_slice_markdown(s)
