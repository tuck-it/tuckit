import pytest
from datetime import timedelta
from django.utils import timezone

from tuckit.core.models import Org, Slice, Workspace
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.bites import create_bite
from tuckit.core.services.slices import create_slice
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
def workspace(db):
    org = Org.objects.create(name="Acme", slug="acme")
    return Workspace.objects.create(org=org, name="MyProduct", slug="myproduct", description="A demo product")


@pytest.mark.django_db
def test_project_state_buckets_by_status(workspace):
    area = create_area(workspace, "Backend")
    create_slice(area, "Auth", status="shipped")
    building = create_slice(area, "Payments", status="building")
    create_bite(building, "Stripe", status="doing")
    create_bite(building, "Done bite", status="done")
    create_slice(area, "Notifications", status="planned")
    create_slice(area, "Someday idea", status="idea", tags=["someday"])

    state = get_project_state(workspace)
    assert state["product"]["description"] == "A demo product"
    a = state["areas"][0]
    assert [s["title"] for s in a["shipped"]] == ["Auth"]
    assert [s["title"] for s in a["building"]] == ["Payments"]
    assert [b["title"] for b in a["building"][0]["open_bites"]] == ["Stripe"]  # 'done' excluded
    assert [s["title"] for s in a["roadmap"]] == ["Notifications"]
    assert [s["title"] for s in a["someday"]] == ["Someday idea"]


@pytest.mark.django_db
def test_project_state_can_scope_to_one_area(workspace):
    a1 = create_area(workspace, "Backend")
    create_area(workspace, "Frontend")
    create_slice(a1, "Auth", status="shipped")
    state = get_project_state(workspace, area=a1)
    assert len(state["areas"]) == 1
    assert state["areas"][0]["slug"] == a1.slug


@pytest.mark.django_db
def test_render_slice_markdown_includes_spec_and_bites(workspace):
    area = create_area(workspace, "Backend")
    s = create_slice(area, "Auth", spec="Support OAuth login.", status="building", tags=["feature"])
    create_bite(s, "JWT", status="done")
    create_bite(s, "Social login", status="todo")

    md = render_slice_markdown(s)
    assert "# Auth" in md
    assert "Support OAuth login." in md
    assert "- [x] JWT" in md
    assert "- [ ] Social login" in md
    assert "#feature" in md


@pytest.mark.django_db
def test_someday_slice_is_exclusive_to_someday_bucket(workspace):
    area = create_area(workspace, "Backend")
    create_slice(area, "Planned someday", status="planned", tags=["someday"])
    create_slice(area, "Plain planned", status="planned")
    state = get_project_state(workspace)
    a = state["areas"][0]
    assert [s["title"] for s in a["someday"]] == ["Planned someday"]
    # the #someday slice must NOT also appear in roadmap:
    assert [s["title"] for s in a["roadmap"]] == ["Plain planned"]


@pytest.mark.django_db
def test_counts_and_dropped_bite_excluded(workspace):
    area = create_area(workspace, "Backend")
    shipped = create_slice(area, "Auth", status="shipped")
    building = create_slice(area, "Payments", status="building")
    create_bite(building, "Open", status="doing")
    create_bite(building, "Done", status="done")
    create_bite(building, "Dropped", status="dropped")
    state = get_project_state(workspace)
    a = state["areas"][0]
    # only the 'doing' bite is open; done + dropped excluded:
    assert [b["title"] for b in a["building"][0]["open_bites"]] == ["Open"]
    assert a["counts"]["open_bites"] == 1
    assert a["counts"]["shipped"] == 1


@pytest.mark.django_db
def test_attention_flags_stale_inbox_and_stalled_building():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    inbox = get_or_create_triage(ws)
    backend = create_area(ws, "Backend")
    stale_in = create_slice(inbox, "old capture")
    fresh_in = create_slice(inbox, "new capture")
    stalled = create_slice(backend, "in flight", status="building")
    old = timezone.now() - timedelta(days=STALE_DAYS + 1)
    Slice.objects.filter(pk__in=[stale_in.pk, stalled.pk]).update(updated_at=old)
    items = attention_items(ws)
    got = {(it["slice"].id, it["reason"]) for it in items}
    assert (stale_in.id, "triage_stale") in got
    assert (stalled.id, "building_stalled") in got
    assert fresh_in.id not in {it["slice"].id for it in items}


@pytest.mark.django_db
def test_home_state_buckets_across_areas_someday_excluded():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    a1 = create_area(ws, "Backend"); a2 = create_area(ws, "Frontend")
    create_slice(a1, "pay", status="building")
    create_slice(a2, "ui", status="building")
    create_slice(a1, "next", status="planned")
    create_slice(a2, "later", status="idea", tags=["someday"])
    st = home_state(ws)
    assert {s.title for s in st["building"]} == {"pay", "ui"}
    assert {s.title for s in st["planned"]} == {"next"}
    assert {s.title for s in st["someday"]} == {"later"}
    assert "later" not in {s.title for s in st["ideas"]}


@pytest.mark.django_db
def test_attention_items_include_reason_and_days():
    from tuckit.core.management.commands.bootstrap import ensure_bootstrap

    ws, _ = ensure_bootstrap()
    inbox = get_or_create_triage(ws)
    s = create_slice(inbox, "오래된 캡처", status="idea")
    old = timezone.now() - timedelta(days=11)
    Slice.objects.filter(pk=s.pk).update(updated_at=old)

    items = attention_items(ws)
    hit = [it for it in items if it["slice"].id == s.id]
    assert hit, "stale inbox slice should surface"
    assert hit[0]["reason"] == "triage_stale"
    assert hit[0]["days"] == 11


@pytest.mark.django_db
def test_roadmap_state_buckets_non_triage_slices():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    a = create_area(ws, "Backend")
    create_slice(a, "idea one", status="idea")
    create_slice(a, "planned one", status="planned")
    create_slice(a, "building one", status="building")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "dropped one", status="dropped")
    create_slice(get_or_create_triage(ws), "captured", status="idea")  # triage excluded
    rs = roadmap_state(ws)
    assert [s.title for s in rs["idea"]] == ["idea one"]        # triage 'captured' excluded
    assert [s.title for s in rs["planned"]] == ["planned one"]
    assert [s.title for s in rs["building"]] == ["building one"]
    assert [s.title for s in rs["shipped"]] == ["shipped one"]
    assert "dropped" not in rs                                   # dropped never bucketed


@pytest.mark.django_db
def test_in_progress_state_has_building_slices_and_doing_bites():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    a = create_area(ws, "Backend")
    s = create_slice(a, "building slice", status="building")
    create_slice(a, "idea slice", status="idea")
    create_bite(s, "doing bite", status="doing")
    create_bite(s, "todo bite", status="todo")
    st = in_progress_state(ws)
    assert [x.title for x in st["slices"]] == ["building slice"]
    assert [x.title for x in st["bites"]] == ["doing bite"]


@pytest.mark.django_db
def test_roadmap_and_in_progress_sort_by_area_name():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    zeta = create_area(ws, "Zeta")
    alpha = create_area(ws, "Alpha")
    # Created Zeta-first, but both functions must return them Alpha-first (sort
    # key is (area name, rank)). Guards against the sort key being dropped/reversed.
    create_slice(zeta, "z build", status="building")
    create_slice(alpha, "a build", status="building")
    assert [s.title for s in roadmap_state(ws)["building"]] == ["a build", "z build"]
    assert [s.title for s in in_progress_state(ws)["slices"]] == ["a build", "z build"]


@pytest.mark.django_db
def test_home_state_excludes_attention_from_building():
    from tuckit.core.management.commands.bootstrap import ensure_bootstrap

    ws, _ = ensure_bootstrap()
    a = create_area(ws, "제품")
    s = create_slice(a, "정체된 작업", status="building")
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=9))

    state = home_state(ws)
    assert any(it["slice"].id == s.id for it in state["attention"])
    assert all(b.id != s.id for b in state["building"]), "stalled building must not double-appear"


@pytest.mark.django_db
def test_cap_shipped_count_mode(workspace):
    workspace.shipped_board_mode = "count"
    workspace.shipped_board_limit = 2
    a = create_area(workspace, "A")
    for i in range(5):
        create_slice(a, f"s{i}", status="shipped")
    shipped = roadmap_state(workspace)["shipped"]
    visible, total = cap_shipped(workspace, shipped)
    assert total == 5
    assert len(visible) == 2


@pytest.mark.django_db
def test_cap_shipped_days_mode_excludes_old(workspace):
    workspace.shipped_board_mode = "days"
    workspace.shipped_board_limit = 30
    a = create_area(workspace, "A")
    recent = create_slice(a, "recent", status="shipped")
    old = create_slice(a, "old", status="shipped")
    old.completed_at = timezone.now() - timedelta(days=90)
    old.save(update_fields=["completed_at"])
    shipped = roadmap_state(workspace)["shipped"]
    visible, total = cap_shipped(workspace, shipped)
    assert total == 2
    titles = {s.title for s in visible}
    assert "recent" in titles and "old" not in titles


@pytest.mark.django_db
def test_shipped_sorted_newest_first(workspace):
    a = create_area(workspace, "A")
    first = create_slice(a, "first", status="shipped")
    second = create_slice(a, "second", status="shipped")
    first.completed_at = timezone.now() - timedelta(days=5)
    first.save(update_fields=["completed_at"])
    shipped = roadmap_state(workspace)["shipped"]
    assert [s.title for s in shipped][:2] == ["second", "first"]


@pytest.mark.django_db
def test_roadmap_board_view_reports_overflow(workspace):
    workspace.shipped_board_mode = "count"
    workspace.shipped_board_limit = 1
    a = create_area(workspace, "A")
    create_slice(a, "s1", status="shipped")
    create_slice(a, "s2", status="shipped")
    view = roadmap_board_view(workspace)
    assert view["shipped_total"] == 2
    assert view["shipped_hidden"] == 1
    shipped_group = dict(view["groups"])["shipped"]
    assert len(shipped_group) == 1


def test_snapshot_today_first_day_has_no_deltas(workspace):
    from tuckit.core.services.state import snapshot_today
    from tuckit.core.models import WorkspaceStatSnapshot
    area = create_area(workspace, "Backend")
    create_slice(area, "A", status="building")
    create_slice(area, "B", status="planned")
    out = snapshot_today(workspace, home_state(workspace))
    assert out["building"] == {"value": 1, "delta": None}
    assert out["backlog"]["value"] == 1
    assert out["backlog"]["delta"] is None
    # exactly one row was written for today
    assert WorkspaceStatSnapshot.objects.filter(workspace=workspace).count() == 1


def test_snapshot_today_is_idempotent_per_day(workspace):
    from tuckit.core.services.state import snapshot_today
    from tuckit.core.models import WorkspaceStatSnapshot
    area = create_area(workspace, "Backend")
    create_slice(area, "A", status="building")
    snapshot_today(workspace, home_state(workspace))
    snapshot_today(workspace, home_state(workspace))
    assert WorkspaceStatSnapshot.objects.filter(workspace=workspace).count() == 1


def test_snapshot_today_delta_vs_prior_day(workspace):
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    from tuckit.core.services.state import snapshot_today
    from tuckit.core.models import WorkspaceStatSnapshot
    area = create_area(workspace, "Backend")
    create_slice(area, "A", status="building")
    # simulate yesterday's snapshot: 3 building
    yesterday = _tz.localdate() - _td(days=1)
    WorkspaceStatSnapshot.objects.create(
        workspace=workspace, date=yesterday, building_ct=3, backlog_ct=0,
        shipped_week_ct=0, attention_ct=0,
    )
    out = snapshot_today(workspace, home_state(workspace))
    assert out["building"] == {"value": 1, "delta": -2}  # 1 today vs 3 yesterday
