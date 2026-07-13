import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.models import Org, Slice, Workspace


@pytest.mark.django_db
def test_board_has_swap_target_id(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "B")
    create_slice(a, "one", status="building")
    body = client_local.get(f"{p}/areas/{a.slug}/?view=board").content.decode()
    assert 'id="board"' in body
    assert 'class="board"' in body

@pytest.mark.django_db
def test_board_view_renders_columns(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "B")
    create_slice(a, "결제", status="building")
    resp = client_local.get(f"{p}/areas/{a.slug}/?view=board")
    body = resp.content.decode()
    assert "결제" in body
    assert 'data-status="building"' in body

@pytest.mark.django_db
def test_board_column_head_has_dot_and_count(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "제품")
    create_slice(a, "카드 A", status="building")
    body = client_local.get(f"{p}/areas/{a.slug}/?view=board").content.decode()
    assert "board-col-head" in body
    assert "status-dot--building" in body

@pytest.mark.django_db
def test_move_changes_status(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "B")
    s = create_slice(a, "결제", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "building"}, HTTP_HX_REQUEST="true")
    assert resp.status_code in (200, 204)
    assert Slice.objects.get(pk=s.id).status == "building"

@pytest.mark.django_db
def test_move_reorders_within_column(client_local, workspace):
    a = create_area(workspace, "B")
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s1 = create_slice(a, "one", status="planned")
    s2 = create_slice(a, "two", status="planned")
    # move s2 before s1
    client_local.post(f"{p}/slices/{s2.id}/move", {"status": "planned", "before_id": s1.id}, HTTP_HX_REQUEST="true")
    ordered = list(Slice.objects.filter(area=a, status="planned").order_by("rank"))
    assert [x.id for x in ordered] == [s2.id, s1.id]

@pytest.mark.django_db
def test_move_invalid_status_returns_400_and_unchanged(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "B")
    s = create_slice(a, "결제", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "blocked"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Slice.objects.get(pk=s.id).status == "planned"

@pytest.mark.django_db
def test_move_foreign_neighbor_404s_without_change(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "B")
    s = create_slice(a, "결제", status="planned")
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_ws = Workspace.objects.create(org=other_org, name="Other", slug="other")
    other_area = create_area(other_ws, "Other Area")
    n = create_slice(other_area, "foreign", status="planned")
    resp = client_local.post(
        f"{p}/slices/{s.id}/move",
        {"status": "building", "before_id": n.id},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 404
    assert Slice.objects.get(pk=s.id).status == "planned"


@pytest.mark.django_db
def test_card_has_status_move_control(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "B")
    create_slice(a, "card one", status="building")
    body = client_local.get(f"{p}/areas/{a.slug}/?view=board").content.decode()
    assert 'aria-label="Move to status"' in body
    assert 'class="card-move"' in body


@pytest.mark.django_db
def test_move_via_hx_returns_board_html(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "B")
    s = create_slice(a, "movable", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "building"},
                             HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="board"' in body                    # re-rendered board
    assert Slice.objects.get(pk=s.id).status == "building"


@pytest.mark.django_db
def test_move_without_hx_returns_204(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "B")
    s = create_slice(a, "movable", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "building"})
    assert resp.status_code == 204
    assert Slice.objects.get(pk=s.id).status == "building"


@pytest.mark.django_db
def test_roadmap_tab_defaults_to_cross_area_board(client_local, workspace):
    """The Board tab (web:roadmap) now defaults to a workspace-wide kanban that
    labels each card with its parent area."""
    p = f"/{workspace.org.slug}/{workspace.slug}"
    design = create_area(workspace, "Design")
    core = create_area(workspace, "Core")
    create_slice(design, "polish empty states", status="building")
    create_slice(core, "slice move api", status="planned")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert 'id="board"' in body                     # kanban, not the flat list
    assert 'data-status="building"' in body
    assert 'data-status="planned"' in body
    assert 'class="card-area"' in body              # parent area surfaced
    assert "Design" in body and "Core" in body      # both areas' cards mixed in


@pytest.mark.django_db
def test_roadmap_tab_list_view_still_available(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    create_slice(a, "list-view slice", status="building")
    body = client_local.get(f"{p}/roadmap/?view=list").content.decode()
    assert "roadmap-dist" in body                   # the distribution strip
    assert 'id="board"' not in body                 # not the kanban
    assert "list-view slice" in body


@pytest.mark.django_db
def test_workspace_scope_move_rerenders_all_areas(client_local, workspace):
    """A move from the Board tab (?scope=workspace) re-renders every area's
    cards, not just the moved slice's area."""
    p = f"/{workspace.org.slug}/{workspace.slug}"
    design = create_area(workspace, "Design")
    core = create_area(workspace, "Core")
    moved = create_slice(design, "moved slice", status="planned")
    create_slice(core, "other-area slice", status="idea")
    resp = client_local.post(
        f"{p}/slices/{moved.id}/move?scope=workspace",
        {"status": "building"}, HTTP_HX_REQUEST="true",
    )
    body = resp.content.decode()
    assert resp.status_code == 200
    assert Slice.objects.get(pk=moved.id).status == "building"
    assert "other-area slice" in body               # foreign area still present
    assert 'class="card-area"' in body


@pytest.mark.django_db
def test_board_caps_shipped_and_links_to_all(client_local, workspace):
    workspace.shipped_board_mode = "count"
    workspace.shipped_board_limit = 1
    workspace.save(update_fields=["shipped_board_mode", "shipped_board_limit"])
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "shipped two", status="shipped")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "View all shipped (2)" in body
    assert 'href="?view=list&status=shipped"' in body


@pytest.mark.django_db
def test_status_filter_shows_all_shipped_flat(client_local, workspace):
    workspace.shipped_board_limit = 1
    workspace.save(update_fields=["shipped_board_limit"])
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "shipped two", status="shipped")
    body = client_local.get(f"{p}/roadmap/?view=list&status=shipped").content.decode()
    assert "shipped one" in body and "shipped two" in body   # uncapped
    assert 'id="board"' not in body                          # not the kanban
    assert 'class="card-area"' in body or 'class="row-area"' in body


@pytest.mark.django_db
def test_status_filter_is_generic(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Core")
    create_slice(a, "building thing", status="building")
    body = client_local.get(f"{p}/roadmap/?status=building").content.decode()
    assert "building thing" in body
    assert 'id="board"' not in body


@pytest.mark.django_db
def test_board_no_footer_when_within_limit(client_local, workspace):
    workspace.shipped_board_limit = 8
    workspace.save(update_fields=["shipped_board_limit"])
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    create_slice(a, "only one", status="shipped")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "View all shipped" not in body


def test_board_js_declares_drag_states():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "board.js").read_text()
    assert "ghostClass" in js
    assert "board-col--droppable" in js
    assert 'filter: ".card-move"' in js


def test_app_css_declares_droppable_state():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "app.css").read_text()
    assert ".board-col--droppable" in css
    assert ".slice-card--ghost" in css
