import pytest
from datetime import timedelta
from django.utils import timezone

from tuckit.core.models import Org, Slice, Ticket
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import create_ticket
from tuckit.core.services.state import (
    attention_items,
    cap_shipped,
    home_state,
    in_progress_state,
    roadmap_board_view,
    roadmap_state,
    STALE_DAYS,
    get_project_state,
    render_slice_markdown,
)


@pytest.fixture
def product_org(db):
    return Org.objects.create(name="MyProduct", slug="myproduct", description="A demo product")


@pytest.mark.django_db
def test_project_state_buckets_by_status(product_org):
    product_org.description = "A demo product"
    product_org.save(update_fields=["description", "updated_at"])
    area = create_area(product_org, "Backend")
    create_slice(area, "Auth", status="shipped")
    building = create_slice(area, "Payments", status="building")
    building_plan = create_plan(building, title="Plan")
    create_bite(building_plan, "Stripe", status="doing")
    create_bite(building_plan, "Done bite", status="done")
    create_slice(area, "Notifications", status="planned")
    create_slice(area, "Someday item", status="planned", tags=["someday"])

    state = get_project_state(product_org)
    assert state["org"]["description"] == "A demo product"
    a = state["areas"][0]
    assert [s["title"] for s in a["shipped"]] == ["Auth"]
    assert [s["title"] for s in a["building"]] == ["Payments"]
    assert [b["title"] for b in a["building"][0]["open_bites"]] == ["Stripe"]  # 'done' excluded
    assert [s["title"] for s in a["roadmap"]] == ["Notifications"]
    assert [s["title"] for s in a["someday"]] == ["Someday item"]


@pytest.mark.django_db
def test_project_state_can_scope_to_one_area(product_org):
    a1 = create_area(product_org, "Backend")
    create_area(product_org, "Frontend")
    create_slice(a1, "Auth", status="shipped")
    state = get_project_state(product_org, area=a1)
    assert len(state["areas"]) == 1
    assert state["areas"][0]["slug"] == a1.slug


@pytest.mark.django_db
def test_render_slice_markdown_includes_spec_and_bites(product_org):
    area = create_area(product_org, "Backend")
    s = create_slice(area, "Auth", spec="Support OAuth login.", status="building", tags=["feature"])
    p = create_plan(s, title="Plan")
    create_bite(p, "JWT", status="done")
    create_bite(p, "Social login", status="todo")

    md = render_slice_markdown(s)
    assert "# Auth" in md
    assert "Support OAuth login." in md
    assert "- [x] JWT" in md
    assert "- [ ] Social login" in md
    assert "#feature" in md


@pytest.mark.django_db
def test_render_slice_markdown_includes_bite_body(product_org):
    area = create_area(product_org, "Backend")
    s = create_slice(area, "Auth")
    p = create_plan(s, title="Plan")
    create_bite(p, "JWT", body="use RS256 keys")
    md = render_slice_markdown(s)
    assert "- [ ] JWT" in md
    assert "use RS256 keys" in md


@pytest.mark.django_db
def test_someday_slice_is_exclusive_to_someday_bucket(product_org):
    area = create_area(product_org, "Backend")
    create_slice(area, "Planned someday", status="planned", tags=["someday"])
    create_slice(area, "Plain planned", status="planned")
    state = get_project_state(product_org)
    a = state["areas"][0]
    assert [s["title"] for s in a["someday"]] == ["Planned someday"]
    # the #someday slice must NOT also appear in roadmap:
    assert [s["title"] for s in a["roadmap"]] == ["Plain planned"]


@pytest.mark.django_db
def test_counts_and_dropped_bite_excluded(product_org):
    area = create_area(product_org, "Backend")
    shipped = create_slice(area, "Auth", status="shipped")
    building = create_slice(area, "Payments", status="building")
    building_plan = create_plan(building, title="Plan")
    create_bite(building_plan, "Open", status="doing")
    create_bite(building_plan, "Done", status="done")
    create_bite(building_plan, "Dropped", status="dropped")
    state = get_project_state(product_org)
    a = state["areas"][0]
    # only the 'doing' bite is open; done + dropped excluded:
    assert [b["title"] for b in a["building"][0]["open_bites"]] == ["Open"]
    assert a["counts"]["open_bites"] == 1
    assert a["counts"]["shipped"] == 1


@pytest.mark.django_db
def test_attention_flags_stale_ticket_and_stalled_building():
    org = Org.objects.create(name="Acme", slug="acme")
    backend = create_area(org, "Backend")
    stale_ticket = create_ticket(org, "old capture")
    fresh_ticket = create_ticket(org, "new capture")
    stalled = create_slice(backend, "in flight", status="building")
    old = timezone.now() - timedelta(days=STALE_DAYS + 1)
    Ticket.objects.filter(pk=stale_ticket.pk).update(created_at=old)
    Slice.objects.filter(pk=stalled.pk).update(updated_at=old)
    items = attention_items(org)
    got = {
        ((it["ticket"].id if "ticket" in it else it["slice"].id), it["reason"])
        for it in items
    }
    assert (stale_ticket.id, "ticket_stale") in got
    assert (stalled.id, "building_stalled") in got
    ticket_ids = {it["ticket"].id for it in items if "ticket" in it}
    assert fresh_ticket.id not in ticket_ids


@pytest.mark.django_db
def test_home_state_buckets_across_areas_someday_excluded():
    org = Org.objects.create(name="Acme", slug="acme")
    a1 = create_area(org, "Backend"); a2 = create_area(org, "Frontend")
    create_slice(a1, "pay", status="building")
    create_slice(a2, "ui", status="building")
    create_slice(a1, "next", status="planned")
    create_slice(a2, "later", status="planned", tags=["someday"])
    st = home_state(org)
    assert {s.title for s in st["building"]} == {"pay", "ui"}
    assert {s.title for s in st["planned"]} == {"next"}
    assert {s.title for s in st["someday"]} == {"later"}
    assert "ideas" not in st  # the 'idea' status/bucket is retired


@pytest.mark.django_db
def test_attention_items_include_reason_and_days():
    from tuckit.core.management.commands.bootstrap import ensure_bootstrap

    org, _ = ensure_bootstrap()
    t = create_ticket(org, "Old capture")
    old = timezone.now() - timedelta(days=11)
    Ticket.objects.filter(pk=t.pk).update(created_at=old)

    items = attention_items(org)
    hit = [it for it in items if it.get("ticket") and it["ticket"].id == t.id]
    assert hit, "stale ticket should surface"
    assert hit[0]["reason"] == "ticket_stale"
    assert hit[0]["days"] == 11


@pytest.mark.django_db
def test_roadmap_state_buckets_by_status():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    create_slice(a, "planned one", status="planned")
    create_slice(a, "building one", status="building")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "dropped one", status="dropped")
    rs = roadmap_state(org)
    assert [s.title for s in rs["planned"]] == ["planned one"]
    assert [s.title for s in rs["building"]] == ["building one"]
    assert [s.title for s in rs["shipped"]] == ["shipped one"]
    assert "dropped" not in rs                                   # dropped never bucketed
    assert "idea" not in rs                                      # the 'idea' status is retired


@pytest.mark.django_db
def test_in_progress_state_has_building_slices_and_doing_bites():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s = create_slice(a, "building slice", status="building")
    create_slice(a, "planned slice", status="planned")
    p = create_plan(s, title="Plan")
    create_bite(p, "doing bite", status="doing")
    create_bite(p, "todo bite", status="todo")
    st = in_progress_state(org)
    assert [x.title for x in st["slices"]] == ["building slice"]
    assert [x.title for x in st["bites"]] == ["doing bite"]


@pytest.mark.django_db
def test_roadmap_and_in_progress_sort_by_area_name():
    org = Org.objects.create(name="Acme", slug="acme")
    zeta = create_area(org, "Zeta")
    alpha = create_area(org, "Alpha")
    # Created Zeta-first, but both functions must return them Alpha-first (sort
    # key is (area name, rank)). Guards against the sort key being dropped/reversed.
    create_slice(zeta, "z build", status="building")
    create_slice(alpha, "a build", status="building")
    assert [s.title for s in roadmap_state(org)["building"]] == ["a build", "z build"]
    assert [s.title for s in in_progress_state(org)["slices"]] == ["a build", "z build"]


@pytest.mark.django_db
def test_home_state_excludes_attention_from_building():
    from tuckit.core.management.commands.bootstrap import ensure_bootstrap

    org, _ = ensure_bootstrap()
    a = create_area(org, "Product")
    s = create_slice(a, "Stalled work", status="building")
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=9))

    state = home_state(org)
    assert any(it["slice"].id == s.id for it in state["attention"])
    assert all(b.id != s.id for b in state["building"]), "stalled building must not double-appear"


@pytest.mark.django_db
def test_cap_shipped_count_mode(product_org):
    product_org.shipped_board_mode = "count"
    product_org.shipped_board_limit = 2
    a = create_area(product_org, "A")
    for i in range(5):
        create_slice(a, f"s{i}", status="shipped")
    shipped = roadmap_state(product_org)["shipped"]
    visible, total = cap_shipped(product_org, shipped)
    assert total == 5
    assert len(visible) == 2


@pytest.mark.django_db
def test_cap_shipped_days_mode_excludes_old(product_org):
    product_org.shipped_board_mode = "days"
    product_org.shipped_board_limit = 30
    a = create_area(product_org, "A")
    recent = create_slice(a, "recent", status="shipped")
    old = create_slice(a, "old", status="shipped")
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
    first = create_slice(a, "first", status="shipped")
    second = create_slice(a, "second", status="shipped")
    first.completed_at = timezone.now() - timedelta(days=5)
    first.save(update_fields=["completed_at"])
    shipped = roadmap_state(product_org)["shipped"]
    assert [s.title for s in shipped][:2] == ["second", "first"]


@pytest.mark.django_db
def test_roadmap_board_view_reports_overflow(product_org):
    product_org.shipped_board_mode = "count"
    product_org.shipped_board_limit = 1
    a = create_area(product_org, "A")
    create_slice(a, "s1", status="shipped")
    create_slice(a, "s2", status="shipped")
    view = roadmap_board_view(product_org)
    assert view["shipped_total"] == 2
    assert view["shipped_hidden"] == 1
    shipped_group = dict(view["groups"])["shipped"]
    assert len(shipped_group) == 1


def test_snapshot_today_first_day_has_no_deltas(product_org):
    from tuckit.core.services.state import snapshot_today
    from tuckit.core.models import OrgStatSnapshot
    area = create_area(product_org, "Backend")
    create_slice(area, "A", status="building")
    create_slice(area, "B", status="planned")
    out = snapshot_today(product_org, home_state(product_org))
    assert out["building"] == {"value": 1, "delta": None}
    assert out["backlog"]["value"] == 1
    assert out["backlog"]["delta"] is None
    # exactly one row was written for today
    assert OrgStatSnapshot.objects.filter(org=product_org).count() == 1


def test_snapshot_today_is_idempotent_per_day(product_org):
    from tuckit.core.services.state import snapshot_today
    from tuckit.core.models import OrgStatSnapshot
    area = create_area(product_org, "Backend")
    create_slice(area, "A", status="building")
    snapshot_today(product_org, home_state(product_org))
    snapshot_today(product_org, home_state(product_org))
    assert OrgStatSnapshot.objects.filter(org=product_org).count() == 1


def test_snapshot_today_delta_vs_prior_day(product_org):
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    from tuckit.core.services.state import snapshot_today
    from tuckit.core.models import OrgStatSnapshot
    area = create_area(product_org, "Backend")
    create_slice(area, "A", status="building")
    # simulate yesterday's snapshot: 3 building
    yesterday = _tz.localdate() - _td(days=1)
    OrgStatSnapshot.objects.create(
        org=product_org, date=yesterday, building_ct=3, backlog_ct=0,
        shipped_week_ct=0, attention_ct=0,
    )
    out = snapshot_today(product_org, home_state(product_org))
    assert out["building"] == {"value": 1, "delta": -2}  # 1 today vs 3 yesterday


@pytest.mark.django_db
def test_render_slice_markdown_includes_plan_and_constraints(product_org):
    from tuckit.core.services.plans import create_plan
    area = create_area(product_org, "Backend")
    s = create_slice(area, "Auth", spec="design")
    create_plan(s, body="Goal: ship auth", constraints="no billing")
    md = render_slice_markdown(s)
    assert "## Plan" in md and "Goal: ship auth" in md
    assert "### Constraints" in md and "no billing" in md


@pytest.mark.django_db
def test_render_slice_markdown_renders_every_plan(product_org):
    from tuckit.core.services.plans import create_plan
    area = create_area(product_org, "Backend")
    s = create_slice(area, "Auth", spec="design")
    p1 = create_plan(s, title="Backend plan", body="Backend goal", constraints="no billing")
    p2 = create_plan(s, title="Frontend plan", body="Frontend goal")
    create_bite(p1, "Backend bite")
    create_bite(p2, "Frontend bite")

    md = render_slice_markdown(s)

    assert "## Backend plan" in md
    assert "Backend goal" in md
    assert "### Constraints" in md and "no billing" in md
    assert "- [ ] Backend bite" in md

    assert "## Frontend plan" in md
    assert "Frontend goal" in md
    assert "- [ ] Frontend bite" in md


@pytest.mark.django_db
def test_project_state_names_the_org_not_a_product(org):
    org.description = "our company"
    org.save(update_fields=["description", "updated_at"])
    state = get_project_state(org)
    assert "product" not in state
    assert state["org"] == {"name": org.name, "description": "our company"}


@pytest.mark.django_db
def test_slice_markdown_lists_provenance_with_origin_first():
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.state import render_slice_markdown
    from tuckit.core.services.tickets import absorb_ticket, create_ticket, promote_ticket

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    origin = create_ticket(org, "Origin", area=area)
    s = promote_ticket(origin)
    extra = create_ticket(org, "Extra", area=area)
    absorb_ticket(extra, s)

    md = render_slice_markdown(s)
    line = next(l for l in md.splitlines() if l.startswith("From:"))
    assert f"acme-{origin.number} (origin)" in line
    assert f"acme-{extra.number}" in line
    # origin leads, so the ref that names the slice reads first
    assert line.index(f"acme-{origin.number}") < line.index(f"acme-{extra.number}")


@pytest.mark.django_db
def test_slice_markdown_omits_provenance_when_unlinked():
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.state import render_slice_markdown

    org = Org.objects.create(name="Acme", slug="acme")
    s = create_slice(create_area(org, "Backend"), "Direct")
    assert "From:" not in render_slice_markdown(s)


@pytest.mark.django_db
def test_slice_markdown_reports_the_stage_under_status():
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.state import render_slice_markdown

    org = Org.objects.create(name="Acme", slug="acme")
    s = create_slice(create_area(org, "Backend"), "Blank")

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
    s = create_slice(create_area(org, "Backend"), "Done", status="shipped")

    md = render_slice_markdown(s)
    assert "Stage: shipped" in md
    assert "needs_design" not in md
