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
    body = client_local.get(f"{p}/areas/{a.slug}/?view=board").content.decode()
    assert 'id="board"' in body
    assert 'class="board"' in body

@pytest.mark.django_db
def test_board_view_renders_columns(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    create_slice(a, "Payment", status="building")
    resp = client_local.get(f"{p}/areas/{a.slug}/?view=board")
    body = resp.content.decode()
    assert "Payment" in body
    assert 'data-status="building"' in body

@pytest.mark.django_db
def test_board_column_head_has_dot_and_count(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    a = create_area(org, "Product")
    create_slice(a, "Card A", status="building")
    body = client_local.get(f"{p}/areas/{a.slug}/?view=board").content.decode()
    assert "board-col-head" in body
    assert "status-dot--building" in body

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
    """The Board tab (web:roadmap) now defaults to a workspace-wide kanban that
    labels each card with its parent area."""
    p = f"/{org.slug}"
    design = create_area(org, "Design")
    core = create_area(org, "Core")
    create_slice(design, "polish empty states", status="building")
    create_slice(core, "slice move api", status="planned")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert 'id="board"' in body                     # kanban, not the flat list
    assert 'data-status="building"' in body
    assert 'data-status="planned"' in body
    assert 'class="card-area"' in body              # parent area surfaced
    assert "Design" in body and "Core" in body      # both areas' cards mixed in


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
    assert "View all shipped (2)" in body
    assert 'href="?view=list&status=shipped"' in body


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
def test_board_no_footer_when_within_limit(client_local, org):
    org.shipped_board_limit = 8
    org.save(update_fields=["shipped_board_limit", "updated_at"])
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    create_slice(a, "only one", status="shipped")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "View all shipped" not in body


def test_board_js_declares_drag_states():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "board.js").read_text()
    assert "ghostClass" in js
    assert "board-col--droppable" in js


def test_app_css_declares_droppable_state():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "app.css").read_text()
    assert ".board-col--droppable" in css
    assert ".slice-card--ghost" in css


@pytest.mark.django_db
def test_board_days_mode_shipped_outside_window_still_counts_as_slice(client_local, org):
    """In days mode, a shipped slice completed outside the window is capped out
    of the visible column, but it still counts as "a slice exists" — the board
    must not show the empty-board hint alongside the shipped overflow footer."""
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
    assert "View all shipped (1)" in body
