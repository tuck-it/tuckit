from datetime import timedelta

import pytest
from django.utils import timezone

from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import add_bites
from tuckit.core.services.slices import create_slice
from tuckit.core.models import Org, Slice


@pytest.mark.django_db
def test_board_has_swap_target_id(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    create_slice(a.org, area=a, title="one", status="open")
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert 'id="board"' in body
    assert 'class="board"' in body
    assert 'data-stage="needs_design"' in body   # "one" slice has no spec

@pytest.mark.django_db
def test_board_view_renders_columns(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    create_slice(a.org, area=a, title="Payment", status="open")
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
    create_slice(a.org, area=a, title="Card A", status="open")
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert "board-col-head" in body
    assert "status-dot--needs_design" in body

@pytest.mark.django_db
def test_move_changes_status(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a.org, area=a, title="Payment", status="open")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "shipped"}, HTTP_HX_REQUEST="true")
    assert resp.status_code in (200, 204)
    assert Slice.objects.get(pk=s.id).status == "shipped"

@pytest.mark.django_db
def test_move_reorders_within_column(client_local, org):
    a = create_area(org, "B")
    p = f"/{org.slug}"
    s1 = create_slice(a.org, area=a, title="one", status="open")
    s2 = create_slice(a.org, area=a, title="two", status="open")
    # move s2 before s1
    client_local.post(f"{p}/slices/{s2.id}/move", {"status": "open", "before_id": s1.id}, HTTP_HX_REQUEST="true")
    ordered = list(Slice.objects.filter(area=a, status="open").order_by("rank"))
    assert [x.id for x in ordered] == [s2.id, s1.id]

@pytest.mark.django_db
def test_move_invalid_status_returns_400_and_unchanged(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a.org, area=a, title="Payment", status="open")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "blocked"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Slice.objects.get(pk=s.id).status == "open"

@pytest.mark.django_db
def test_move_foreign_neighbor_404s_without_change(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a.org, area=a, title="Payment", status="open")
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_area = create_area(other_org, "Other Area")
    n = create_slice(other_area.org, area=other_area, title="foreign", status="open")
    resp = client_local.post(
        f"{p}/slices/{s.id}/move",
        {"status": "shipped", "before_id": n.id},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 404
    assert Slice.objects.get(pk=s.id).status == "open"


@pytest.mark.django_db
def test_move_without_hx_returns_204(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a.org, area=a, title="movable", status="open")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "shipped"})
    assert resp.status_code == 204
    assert Slice.objects.get(pk=s.id).status == "shipped"


# --- Task 12: the Board's Ship/Drop (drag or button) also announces itself --
#
# slice_move's own response is a bare 204 — SortableJS ignores the body on a
# drag, and this view is always called from the Board (an 'area' roll-up view,
# per htmx.refresh_rollup), so an HX-Refresh full-page reload always follows.
# An HX-Trigger toast fired on the 204 would flash and vanish under that
# reload, so the announcement rides django.contrib.messages instead — the
# same "second channel" Task 10 built for the ticket-deep-link redirect — and
# base.html's `{% for m in messages %}` loop plays it through the SAME
# showToast() on the reloaded page.


@pytest.mark.django_db
def test_move_status_change_queues_a_toast_for_the_next_page_load(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a.org, area=a, title="Payment", status="open")
    resp = client_local.post(f"{p}/slices/{s.id}/move", {"status": "shipped"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert resp.content == b""  # nothing to swap: the announcement is queued, not in this body

    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert "Shipped." in body
    assert "Undo" in body
    # Queued through django.contrib.messages -> played inline via escapejs, so
    # the '=' the URL needs is JS-escaped as = in the source; the browser
    # decodes it back before htmx ever sees the string.
    assert f"/slices/{s.id}/status?undo_status\\u003Dopen" in body  # Undo re-opens it


@pytest.mark.django_db
def test_move_dropping_from_the_board_queues_restore_undo(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "B")
    s = create_slice(a.org, area=a, title="Payment", status="open")
    client_local.post(f"{p}/slices/{s.id}/move", {"status": "dropped"}, HTTP_HX_REQUEST="true")

    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert "Dropped." in body
    assert f"/slices/{s.id}/status?undo_status\\u003Dopen" in body


@pytest.mark.django_db
def test_move_reorder_only_queues_no_toast(client_local, org):
    """A pure drag reorder within the same column changes no status, so it has
    nothing to announce — matching the endpoint's existing "two callers"
    split (status change vs. reorder)."""
    a = create_area(org, "B")
    p = f"/{org.slug}"
    s1 = create_slice(a.org, area=a, title="one", status="open")
    s2 = create_slice(a.org, area=a, title="two", status="open")
    client_local.post(
        f"{p}/slices/{s2.id}/move", {"status": "open", "before_id": s1.id}, HTTP_HX_REQUEST="true"
    )
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert "Shipped." not in body
    assert "Dropped." not in body
    assert "Reopened." not in body
    assert "Restored." not in body


@pytest.mark.django_db
def test_roadmap_tab_defaults_to_cross_area_board(client_local, org):
    """The Board tab (web:roadmap) defaults to a workspace-wide stage pipeline
    that labels each card with its parent area."""
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    design = create_area(org, "Design")
    core = create_area(org, "Core")
    ex = create_slice(design.org, area=design, title="polish empty states", spec="s")
    create_bite(ex, "b", status="doing")   # executing
    create_slice(core.org, area=core, title="slice move api")                            # needs_design
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert 'id="board"' in body
    assert 'data-stage="executing"' in body
    assert 'data-stage="needs_design"' in body
    assert "card-sub" in body                       # area now lives in the meta line
    assert "Design" in body and "Core" in body


@pytest.mark.django_db
def test_roadmap_tab_list_view_still_available(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    create_slice(a.org, area=a, title="list-view slice", status="open")
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
    create_slice(a.org, area=a, title="shipped one", status="shipped")
    create_slice(a.org, area=a, title="shipped two", status="shipped")
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
    create_slice(a.org, area=a, title="shipped one", status="shipped")
    create_slice(a.org, area=a, title="shipped two", status="shipped")
    body = client_local.get(f"{p}/roadmap/?view=list&status=shipped").content.decode()
    assert "shipped one" in body and "shipped two" in body   # uncapped
    assert 'id="board"' not in body                          # not the kanban
    assert 'class="card-area"' in body or 'class="row-area"' in body


@pytest.mark.django_db
def test_status_filter_is_generic(client_local, org):
    """The ?status= filter is shared by every real status value (open/shipped/
    dropped) via the same flat-list surface, not a per-status route."""
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a.org, area=a, title="queued thing", status="open")
    body = client_local.get(f"{p}/roadmap/?status=open").content.decode()
    assert "queued thing" in body
    assert 'id="board"' not in body


@pytest.mark.django_db
def test_status_filter_survives_an_inbox_slice(client_local, org):
    """Regression (Task 6 fix round 1): an area-less (Inbox) slice used to hard
    500 this route — roadmap_state()'s bucket() sorted by `s.area.name`, which
    an unfiled capture doesn't have. This must be a real request through the
    view, not a service-level call, because a service-level test would not
    have caught the crash (the view is what dereferences the template context
    built from roadmap_state())."""
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a.org, area=a, title="filed thing", status="open")
    create_slice(org, title="unfiled capture", status="open")   # no area — Inbox
    resp = client_local.get(f"{p}/roadmap/?status=open")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "filed thing" in body
    assert "unfiled capture" not in body


@pytest.mark.django_db
def test_shipped_link_shows_regardless_of_cap(client_local, org):
    # Shipped is off-board: the header link shows whenever any shipped slice
    # exists, independent of the (now board-irrelevant) cap.
    org.shipped_board_limit = 8
    org.save(update_fields=["shipped_board_limit", "updated_at"])
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    create_slice(a.org, area=a, title="only one", status="shipped")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Shipped (1)" in body
    assert 'data-stage="shipped"' not in body


@pytest.mark.django_db
def test_ready_to_ship_card_has_ship_button(client_local, org):
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    rts = create_slice(a.org, area=a, title="all done", spec="s")
    create_bite(rts, "b", status="done")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Ship it" in body
    assert f'/slices/{rts.id}/move' in body
    assert '"status": "shipped"' in body


@pytest.mark.django_db
def test_every_active_card_has_a_drop_action(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    s = create_slice(a.org, area=a, title="no spec")   # needs_design
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert ">Drop<" in body
    assert '"status": "dropped"' in body


@pytest.mark.django_db
def test_needs_steps_column_badges_needs_steps(client_local, org):
    """needs_plan and needs_bites collapsed into one needs_steps stage (Task 4)
    — a slice with a Plan already attached but no bites still badges the same
    as one with no Plan at all, because Plan no longer factors into stage."""
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a.org, area=a, title="spec only", spec="s")             # needs_steps
    empty = create_slice(a.org, area=a, title="has an empty plan", spec="s")
    create_plan(empty, title="P")                      # still needs_steps
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert body.count("needs steps") == 2


@pytest.mark.django_db
def test_board_partial_has_no_drag_script(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a.org, area=a, title="one")
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
    s = create_slice(a.org, area=a, title="old shipped one", status="shipped")
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
    create_slice(a.org, area=a, title="shipped one", status="shipped")
    body = client_local.get(f"{p}/roadmap/?status=shipped").content.decode()
    assert "← Board" in body
    assert f'href="/{org.slug}/roadmap/"' in body
    assert "shipped one" in body
    assert 'id="board"' not in body


@pytest.mark.django_db
def test_board_renders_stage_columns_and_labels(client_local, org):
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a.org, area=a, title="no spec")                                   # needs_design
    rts = create_slice(a.org, area=a, title="all done", spec="s")
    create_bite(rts, "b", status="done")                         # ready_to_ship
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert 'data-stage="needs_design"' in body
    assert 'data-stage="ready_to_ship"' in body
    assert "Needs design" in body
    assert "Ready to ship" in body


@pytest.mark.django_db
def test_board_dropped_link_appears_with_count(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a.org, area=a, title="live one")
    create_slice(a.org, area=a, title="gone", status="dropped")
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Dropped (1)" in body
    assert 'href="?status=dropped"' in body


@pytest.mark.django_db
def test_roadmap_dropped_status_filter_lists_dropped(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a.org, area=a, title="gone one", status="dropped")
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
    create_slice(a.org, area=a, title="shipped one", status="shipped")
    body = client_local.get(f"{p}/roadmap/?view=board").content.decode()
    assert 'data-stage="shipped"' not in body      # no shipped column
    assert 'href="?status=shipped"' in body        # off-board filter link
    assert "Shipped (1)" in body                    # with total count


@pytest.mark.django_db
def test_card_is_title_centric_no_pills(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Core")
    create_slice(a.org, area=a, title="spec only", spec="s")          # needs_steps
    body = client_local.get(f"{p}/roadmap/?view=board").content.decode()
    assert "card-topline" not in body               # no nested pill row
    assert 'class="card-badge"' not in body         # stage is text, not a pill
    assert "card-sub" in body                        # the single meta line
    assert "needs steps" in body                     # stage hint as text


@pytest.mark.django_db
def test_board_excludes_inbox_slices(client_local, org, area):
    create_slice(org, title="Inbox에 있는 것")
    create_slice(org, area=area, title="보드에 있는 것", spec="설계")
    body = client_local.get(f"/{org.slug}/roadmap/").content.decode()
    assert "보드에 있는 것" in body
    assert "Inbox에 있는 것" not in body


@pytest.mark.django_db
def test_home_in_progress_fills_without_any_plan_object(client_local, org, area):
    """관문 부재 가드 — 이 작업의 핵심 성과다.

    이전에는 executing에 닿으려면 Plan을 먼저 만들어야 했고, 아무도 안 만들어서
    Home의 이 밴드가 사실상 항상 비어 있었다."""
    s = create_slice(org, area=area, title="진행 중", spec="설계됨")
    bites = add_bites(s, [{"title": "a"}, {"title": "b"}])
    from tuckit.core.services.bites import set_bite_status
    set_bite_status(bites[0], "done")

    body = client_local.get(f"/{org.slug}/").content.decode()
    assert "진행 중" in body


@pytest.mark.django_db
def test_home_in_progress_survives_an_executing_inbox_slice(client_local, org, area):
    """Pins the crash: home_state()'s in_progress band sorts with
    key=lambda s: (..., s.area.name, s.rank) over an UNFILTERED
    Slice.objects.filter(org=org). slice_stage() never looks at area, so an
    Inbox slice (area IS NULL) with a spec and one live bite legitimately
    reaches stage == "executing" — and the sort key's `s.area.name`
    dereference 500s Home with AttributeError. Must be a real request through
    the view: a service-level home_state() call alone would not exercise the
    template/response path that Task 6's identical bug class slipped through."""
    from tuckit.core.services.bites import set_bite_status

    filed = create_slice(org, area=area, title="필터된 진행", spec="설계", status="open")
    filed_bites = add_bites(filed, [{"title": "a"}, {"title": "b"}])
    set_bite_status(filed_bites[0], "done")

    inbox = create_slice(org, title="Inbox 진행 중", spec="설계")   # no area
    inbox_bites = add_bites(inbox, [{"title": "a"}, {"title": "b"}])
    set_bite_status(inbox_bites[0], "done")

    resp = client_local.get(f"/{org.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Scoped to the "in progress" band itself: the slice's own creation event
    # legitimately echoes its title in the "since you were away" band above it
    # (target_label), so a whole-page substring check would false-positive.
    marker = "<span>in progress</span>"
    start = body.rindex('<section class="band">', 0, body.index(marker))
    end = body.index("</section>", start)
    in_progress_band = body[start:end]
    assert "필터된 진행" in in_progress_band
    assert "Inbox 진행 중" not in in_progress_band, "an unfiled slice must not reach the in progress band"


@pytest.mark.django_db
def test_roadmap_dropped_filter_excludes_inbox_slices(client_local, org, area):
    """Pins the second crash site: roadmap()'s status="dropped" branch in
    web/views/pages.py queried Slice.objects directly with a DB-level order,
    so no crash — but a dropped Inbox (area IS NULL) slice leaked into the
    list. Must route through filed_slices() like every other filed query."""
    create_slice(org, area=area, title="버려진 필터 슬라이스", status="dropped")
    create_slice(org, title="버려진 Inbox 슬라이스", status="dropped")   # no area
    body = client_local.get(f"/{org.slug}/roadmap/?status=dropped").content.decode()
    assert "버려진 필터 슬라이스" in body
    assert "버려진 Inbox 슬라이스" not in body


