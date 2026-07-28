"""The Inbox screen: area-less open Slices, newest first. Triage is picking an
Area on the row — reversible in both directions, since an empty area_id sends
the slice right back here. There is no Promote/Merge/Dismiss any more; those
verbs belonged to the old Ticket-based Inbox (tests/web/test_capture_triage.py,
retired by this file) and do not have an equivalent for a Slice.

The Ticket triage modal those verbs lived in is gone (Task 10). The Area
page's own "Inbox" strip that briefly forwarded rows to the slice each
capture became is gone too (Task 11) — the Board and the Area page now share
one layout, differing only in header and scope (see test_area.py /
test_board.py). What remains of the old Ticket routes is covered by
test_ticket_deeplink.py.
"""
import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_inbox_lists_only_unfiled_open_slices(client_local, org, area):
    create_slice(org, title="정리 안 됨")
    create_slice(org, area=area, title="정리됨")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert "정리 안 됨" in body
    assert "정리됨" not in body


@pytest.mark.django_db
def test_picking_an_area_files_the_slice(client_local, org, area):
    s = create_slice(org, title="캡처")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": area.id})
    assert r.status_code == 200
    s.refresh_from_db()
    assert s.area_id == area.id


@pytest.mark.django_db
def test_clearing_the_area_sends_it_back_to_the_inbox(client_local, org, area):
    s = create_slice(org, area=area, title="되돌릴 것")
    client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": ""})
    s.refresh_from_db()
    assert s.area_id is None


@pytest.mark.django_db
def test_inbox_rows_show_no_stage_pill(client_local, org):
    create_slice(org, title="캡처")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert "Needs design" not in body      # 전부 needs_design이라 신호가 아니다


# --- reversibility is the point of this task: verify the round trip, not
#     just each direction in isolation ---


@pytest.mark.django_db
def test_filing_then_clearing_round_trips_back_to_the_inbox(client_local, org, area):
    s = create_slice(org, title="왕복")
    p = f"/{org.slug}"
    client_local.post(f"{p}/slices/{s.id}/area", {"area_id": area.id})
    s.refresh_from_db()
    assert s.area_id == area.id

    client_local.post(f"{p}/slices/{s.id}/area", {"area_id": ""})
    s.refresh_from_db()
    assert s.area_id is None
    assert "왕복" in client_local.get(f"{p}/inbox/").content.decode()


@pytest.mark.django_db
def test_filing_into_a_foreign_area_404s(client_local, org):
    other = Org.objects.create(name="Other", slug="other-inbox-org")
    foreign = create_area(other, "Foreign")
    s = create_slice(org, title="크로스 org")
    resp = client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": foreign.id})
    assert resp.status_code == 404
    s.refresh_from_db()
    assert s.area_id is None


@pytest.mark.django_db
def test_area_action_requires_post(client_local, org):
    s = create_slice(org, title="GET 거부")
    resp = client_local.get(f"/{org.slug}/slices/{s.id}/area")
    assert resp.status_code == 405


# --- the toast + undo plumbing (reused from capture's _inbox_result) ---


@pytest.mark.django_db
def test_filing_returns_a_toast_naming_the_area(client_local, org, area):
    s = create_slice(org, title="토스트")
    body = client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": area.id}).content.decode()
    assert f"Filed in {area.name}." in body
    assert 'id="toast"' in body


@pytest.mark.django_db
def test_clearing_returns_a_toast_saying_moved_back(client_local, org, area):
    s = create_slice(org, area=area, title="토스트 2")
    body = client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": ""}).content.decode()
    assert "Moved back to Inbox." in body


@pytest.mark.django_db
def test_undo_after_filing_clears_the_area(client_local, org, area):
    """A bare re-POST to the same endpoint with no body clears the area — the
    Undo button must not carry a stale area_id along after a *filing*."""
    s = create_slice(org, title="파일링 취소")
    body = client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": area.id}).content.decode()
    start = body.index("toast-undo")
    tag = body[body.rindex("<button", 0, start):body.index(">", start)]
    assert f'hx-post="/{org.slug}/slices/{s.id}/area"' in tag
    assert '"area_id": ""' in tag


@pytest.mark.django_db
def test_undo_after_clearing_restores_the_previous_area(client_local, org, area):
    """The tricky direction: undoing a *clear* must re-file into the area it
    just left, not merely re-clear (which would be a no-op Undo)."""
    s = create_slice(org, area=area, title="복구")
    body = client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": ""}).content.decode()
    start = body.index("toast-undo")
    tag = body[body.rindex("<button", 0, start):body.index(">", start)]
    assert f'"area_id": "{area.id}"' in tag


# --- accessibility: 27 identical "Area" labels are useless to a screen reader ---


@pytest.mark.django_db
def test_each_row_select_has_a_distinct_accessible_name(client_local, org):
    create_slice(org, title="First capture")
    create_slice(org, title="Second capture")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert 'aria-label="Area for First capture"' in body
    assert 'aria-label="Area for Second capture"' in body


# --- htmx inherits hx-swap from ancestors; this exact bug class has bitten
#     this codebase before (the deleted triage select 200'd and was discarded).
#     The slice panel's copy of this control has the same guard, in
#     test_slice_detail.py ---


@pytest.mark.django_db
def test_inbox_area_select_declares_its_own_hx_swap(client_local, org):
    create_slice(org, title="스왑 가드")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    start = body.index('class="inbox-area-select"')
    tag = body[body.rindex("<select", 0, start):body.index(">", start)]
    assert 'hx-swap="none"' in tag


# --- one control per row: no Promote/Merge/Dismiss verbs on this screen ---


@pytest.mark.django_db
def test_inbox_row_offers_only_the_area_picker(client_local, org):
    create_slice(org, title="단일 컨트롤")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert "Promote" not in body
    assert "inbox-area-select" in body


@pytest.mark.django_db
def test_inbox_empty_state(client_local, org):
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert "Inbox is empty. Everything is filed." in body


# --- provenance + body preview (fix round 2/5, human ruling): on production
#     24 of 27 Inbox rows are agent-authored with same-shaped titles, so a
#     ref/title/timestamp-only row made them indistinguishable. Both are
#     display only — restoring them must not add a second interactive
#     control to the row. ---


@pytest.mark.django_db
def test_agent_captured_row_shows_the_agent_badge(client_local, org):
    create_slice(org, title="에이전트 캡처", source="agent")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert 'class="source-badge is-agent"' in body
    assert ">agent<" in body


@pytest.mark.django_db
def test_human_captured_row_shows_the_human_badge(client_local, org):
    create_slice(org, title="사람 캡처", source="human")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert 'class="source-badge"' in body
    assert "is-agent" not in body
    assert ">you<" in body


@pytest.mark.django_db
def test_row_shows_a_one_line_spec_summary(client_local, org):
    s = create_slice(org, title="본문 있음",
                      spec="First line of the note.\n\nSecond paragraph nobody should see.")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert "First line of the note." in body
    assert "Second paragraph" not in body
    assert 'class="row-desc"' in body


@pytest.mark.django_db
def test_empty_spec_renders_no_preview_and_no_stray_separator(client_local, org):
    create_slice(org, title="본문 없음", spec="")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert 'class="row-desc"' not in body


@pytest.mark.django_db
def test_row_still_has_exactly_one_interactive_control(client_local, org):
    """The badge and the preview are read-only spans, not a second control —
    the row's only <select>/<button> is the Area picker."""
    create_slice(org, title="컨트롤 하나", spec="a note", source="agent")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    row_start = body.index('class="inbox-row"')
    row_end = body.index("</div>", body.index("</select>", row_start))
    row_html = body[row_start:row_end]
    assert row_html.count("<select") == 1
    assert "<button" not in row_html


# --- closes the Task 8 gap: capture already created Slices, but the Inbox
#     list and the sidebar badge stayed Ticket-based (and therefore frozen)
#     until this task made them read inbox_slices() too ---


@pytest.mark.django_db
def test_a_capture_appears_in_the_inbox_and_moves_the_sidebar_badge(client_local, org):
    client_local.post(f"/{org.slug}/capture", {"title": "새 캡처"}, HTTP_HX_REQUEST="true")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert "새 캡처" in body
    assert 'id="ticket-count"' in body
    assert ">1<" in body


@pytest.mark.django_db
def test_capture_response_swaps_the_new_row_into_the_inbox_list(client_local, org):
    resp = client_local.post(f"/{org.slug}/capture", {"title": "즉시 등장"}, HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert 'id="inbox-list"' in body
    assert "즉시 등장" in body


@pytest.mark.django_db
def test_dropped_or_shipped_slices_never_reach_the_inbox(client_local, org):
    """inbox_slices() filters on status="open" — a dropped or shipped
    area-less slice (edge case: an Area was deleted out from under it) must
    not resurrect as something to triage."""
    from tuckit.core.services.slices import set_slice_status

    s = create_slice(org, title="드롭됨")
    set_slice_status(s, "dropped")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert "드롭됨" not in body
