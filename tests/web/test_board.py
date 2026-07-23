from datetime import timedelta

import pytest
from django.utils import timezone

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.models import Org, Slice


@pytest.mark.django_db
def test_board_has_swap_target_id(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    create_slice(a, "one", status="building")
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert 'id="board"' in body
    assert 'class="board"' in body
    assert 'data-stage="needs_design"' in body   # "one" slice has no spec

@pytest.mark.django_db
def test_board_view_renders_columns(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    create_slice(a, "Payment", status="building")
    resp = client_local.get(f"{p}/areas/{a.slug}/")
    body = resp.content.decode()
    assert "Payment" in body
    assert 'data-stage="needs_design"' in body

@pytest.mark.django_db
def test_board_column_head_has_dot_and_count(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    a = create_area(org, "Product")
    create_slice(a, "Card A", status="building")
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert "board-col-head" in body
    assert "status-dot--needs_design" in body

@pytest.mark.django_db
def test_move_changes_status(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a, "Payment", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "building"}, HTTP_HX_REQUEST="true")
    assert resp.status_code in (200, 204)
    assert Slice.objects.get(pk=s.id).status == "building"

@pytest.mark.django_db
def test_move_reorders_within_column(client_local, org):
    a = create_area(org, "B")
    p = f"/{org.slug}"
    s1 = create_slice(a, "one", status="planned")
    s2 = create_slice(a, "two", status="planned")
    # move s2 before s1
    client_local.post(f"{p}/slices/{s2.id}/move", {"status": "planned", "before_id": s1.id}, HTTP_HX_REQUEST="true")
    ordered = list(Slice.objects.filter(area=a, status="planned").order_by("rank"))
    assert [x.id for x in ordered] == [s2.id, s1.id]

@pytest.mark.django_db
def test_move_invalid_status_returns_400_and_unchanged(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a, "Payment", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "blocked"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Slice.objects.get(pk=s.id).status == "planned"

@pytest.mark.django_db
def test_move_foreign_neighbor_404s_without_change(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a, "Payment", status="planned")
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_area = create_area(other_org, "Other Area")
    n = create_slice(other_area, "foreign", status="planned")
    resp = client_local.post(
        f"{p}/slices/{s.id}/move",
        {"status": "building", "before_id": n.id},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 404
    assert Slice.objects.get(pk=s.id).status == "planned"


@pytest.mark.django_db
def test_move_without_hx_returns_204(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a, "movable", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "building"})
    assert resp.status_code == 204
    assert Slice.objects.get(pk=s.id).status == "building"


@pytest.mark.django_db
def test_roadmap_tab_defaults_to_cross_area_board(client_local, org):
    """The Board tab (web:roadmap) defaults to a workspace-wide stage pipeline
    that labels each card with its parent area."""
    from tuckit.core.services.plans import create_plan
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    design = create_area(org, "Design")
    core = create_area(org, "Core")
    ex = create_slice(design, "polish empty states", spec="s")
    create_bite(create_plan(ex, title="P"), "b", status="doing")   # executing
    create_slice(core, "slice move api")                            # needs_design
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert 'id="board"' in body
    assert 'data-stage="executing"' in body
    assert 'data-stage="needs_design"' in body
    assert 'class="card-area"' in body
    assert "Design" in body and "Core" in body


@pytest.mark.django_db
def test_roadmap_tab_list_view_still_available(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    create_slice(a, "list-view slice", status="building")
    body = client_local.get(f"{p}/roadmap/?view=list").content.decode()
    assert "roadmap-dist" in body                   # the distribution strip
    assert 'id="board"' not in body                 # not the kanban
    assert "list-view slice" in body


@pytest.mark.django_db
def test_board_caps_shipped_and_links_to_all(client_local, org):
    org.shipped_board_mode = "count"
    org.shipped_board_limit = 1
    org.save(update_fields=["shipped_board_mode", "shipped_board_limit", "updated_at"])
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "shipped two", status="shipped")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    # Shipped is off-board now: the header link shows the TOTAL (cap no longer
    # governs a board column), pointing at the ?status=shipped filter view.
    assert "Shipped (2)" in body
    assert 'href="?status=shipped"' in body
    assert 'data-stage="shipped"' not in body


@pytest.mark.django_db
def test_status_filter_shows_all_shipped_flat(client_local, org):
    org.shipped_board_limit = 1
    org.save(update_fields=["shipped_board_limit", "updated_at"])
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "shipped two", status="shipped")
    body = client_local.get(f"{p}/roadmap/?view=list&status=shipped").content.decode()
    assert "shipped one" in body and "shipped two" in body   # uncapped
    assert 'id="board"' not in body                          # not the kanban
    assert 'class="card-area"' in body or 'class="row-area"' in body


@pytest.mark.django_db
def test_status_filter_is_generic(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a, "building thing", status="building")
    body = client_local.get(f"{p}/roadmap/?status=building").content.decode()
    assert "building thing" in body
    assert 'id="board"' not in body


@pytest.mark.django_db
def test_shipped_link_shows_regardless_of_cap(client_local, org):
    # Shipped is off-board: the header link shows whenever any shipped slice
    # exists, independent of the (now board-irrelevant) cap.
    org.shipped_board_limit = 8
    org.save(update_fields=["shipped_board_limit", "updated_at"])
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    create_slice(a, "only one", status="shipped")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Shipped (1)" in body
    assert 'data-stage="shipped"' not in body


@pytest.mark.django_db
def test_ready_to_ship_card_has_ship_button(client_local, org):
    from tuckit.core.services.plans import create_plan
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    rts = create_slice(a, "all done", spec="s")
    create_bite(create_plan(rts, title="P"), "b", status="done")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Ship it" in body
    assert f'/slices/{rts.id}/move' in body
    assert '"status": "shipped"' in body


@pytest.mark.django_db
def test_every_active_card_has_a_drop_action(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    s = create_slice(a, "no spec")   # needs_design
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert ">Drop<" in body
    assert '"status": "dropped"' in body


@pytest.mark.django_db
def test_needs_plan_column_badges_needs_plan_vs_needs_bites(client_local, org):
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a, "spec only", spec="s")             # needs_plan
    empty = create_slice(a, "empty plan", spec="s")
    create_plan(empty, title="P")                      # needs_bites
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "needs plan" in body
    assert "needs bites" in body


@pytest.mark.django_db
def test_board_partial_has_no_drag_script(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a, "one")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "board.js" not in body
    assert "data-move-url" not in body


def test_app_css_board_is_flex_scroll_not_grid_drag():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "app.css").read_text()
    assert "overflow-x: auto" in css          # horizontal scroll board
    assert "repeat(4," not in css             # the hardcoded 4-track grid is gone
    assert ".board-col--droppable" not in css # drag states removed
    assert ".slice-card--ghost" not in css
    assert ".card-ship" in css                 # ship affordance styled


@pytest.mark.django_db
def test_board_days_mode_shipped_outside_window_still_counts_as_slice(client_local, org):
    """In days mode, a shipped slice completed outside the window still counts as
    "a slice exists" — the board must not show the empty-board hint alongside the
    off-board Shipped link."""
    org.shipped_board_mode = "days"
    org.shipped_board_limit = 7
    org.save(update_fields=["shipped_board_mode", "shipped_board_limit", "updated_at"])
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    s = create_slice(a, "old shipped one", status="shipped")
    s.completed_at = timezone.now() - timedelta(days=90)
    s.save(update_fields=["completed_at"])
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Nothing here yet — add a slice" not in body
    assert "Shipped (1)" in body


@pytest.mark.django_db
def test_roadmap_status_filter_uses_shared_partial(client_local, org):
    """roadmap.html and area.html render the same single-status surface. The
    back-link is the only per-page difference, supplied as back_url."""
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    create_slice(a, "shipped one", status="shipped")
    body = client_local.get(f"{p}/roadmap/?status=shipped").content.decode()
    assert "← Board" in body
    assert f'href="/{org.slug}/roadmap/"' in body
    assert "shipped one" in body
    assert 'id="board"' not in body


@pytest.mark.django_db
def test_board_renders_stage_columns_and_labels(client_local, org):
    from tuckit.core.services.plans import create_plan
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a, "no spec")                                   # needs_design
    rts = create_slice(a, "all done", spec="s")
    create_bite(create_plan(rts, title="P"), "b", status="done")  # ready_to_ship
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert 'data-stage="needs_design"' in body
    assert 'data-stage="ready_to_ship"' in body
    assert "Needs design" in body
    assert "Ready to ship" in body


@pytest.mark.django_db
def test_board_dropped_link_appears_with_count(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a, "live one")
    create_slice(a, "gone", status="dropped")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Dropped (1)" in body
    assert 'href="?status=dropped"' in body


@pytest.mark.django_db
def test_roadmap_dropped_status_filter_lists_dropped(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a, "gone one", status="dropped")
    body = client_local.get(f"{p}/roadmap/?status=dropped").content.decode()
    assert "gone one" in body
    assert 'id="board"' not in body     # flat filter list, not the kanban


@pytest.mark.django_db
def test_board_view_is_viewport_bounded(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/roadmap/?view=board").content.decode()
    assert "main--board" in body          # A-model: fixed-height board page
    list_body = client_local.get(f"{p}/roadmap/?view=list").content.decode()
    assert "main--board" not in list_body  # list scrolls normally


@pytest.mark.django_db
def test_shipped_is_offboard_not_a_column(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a, "shipped one", status="shipped")
    body = client_local.get(f"{p}/roadmap/?view=board").content.decode()
    assert 'data-stage="shipped"' not in body      # no shipped column
    assert 'href="?status=shipped"' in body        # off-board filter link
    assert "Shipped (1)" in body                    # with total count


