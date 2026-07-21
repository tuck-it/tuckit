import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import create_ticket
from tuckit.core.models import Slice, Ticket
from tuckit.core.models.org import Org

@pytest.mark.django_db
def test_capture_lands_in_inbox_as_ticket(client_local, org):
    p = f"/{org.slug}"
    client_local.post(f"{p}/capture", {"title": "Retry queue"}, HTTP_HX_REQUEST="true")
    t = Ticket.objects.get(org=org, title="Retry queue")
    assert t.area is None and t.status == "open" and t.source == "human"

@pytest.mark.django_db
def test_inbox_lists_captures(client_local, org):
    p = f"/{org.slug}"
    create_ticket(org, "To clean up")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert "To clean up" in body

@pytest.mark.django_db
def test_ticket_promote_moves_out(client_local, org):
    p = f"/{org.slug}"
    backend = create_area(org, "Backend")
    t = create_ticket(org, "To move")
    client_local.post(f"{p}/tickets/{t.id}/promote", {"area_id": backend.id, "status": "planned"}, HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    s = t.slice
    assert s.area_id == backend.id and s.status == "planned"

@pytest.mark.django_db
def test_area_create_makes_area(client_local, org):
    p = f"/{org.slug}"
    client_local.post(f"{p}/areas/new", {"name": "Backend"}, HTTP_HX_REQUEST="true")
    assert org.areas.filter(name="Backend").exists()

@pytest.mark.django_db
def test_capture_returns_toast_count_and_row(client_local, org):
    # No full-page reload: capture returns OOB swaps for toast, count, and the new row.
    p = f"/{org.slug}"
    resp = client_local.post(f"{p}/capture", {"title": "Quick note"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    # count badge
    assert 'id="triage-count"' in body
    assert ">1<" in body
    # toast
    assert 'id="toast"' in body
    assert "Captured" in body
    # The Inbox list is OOB re-rendered (id-matched, reliable) with the new row;
    # it lands only if that page is open. Three elements carry hx-swap-oob="true";
    # #toast, #triage-count, and #triage-list. The form is hx-swap="none", so
    # anything without hx-swap-oob would be silently dropped in the browser.
    assert 'id="triage-list"' in body
    assert body.count('hx-swap-oob="true"') >= 3
    assert "Quick note" in body
    # list is non-empty now, so the "Triage clean" placeholder must be gone
    assert 'id="triage-empty"' not in body

@pytest.mark.django_db
def test_area_create_returns_oob_area_nav(client_local, org):
    p = f"/{org.slug}"
    resp = client_local.post(f"{p}/areas/new", {"name": "New area"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="area-nav"' in body
    assert 'hx-swap-oob="true"' in body
    assert "New area" in body   # the new area appears in the swapped nav

@pytest.mark.django_db
def test_ticket_promote_invalid_status_returns_400(client_local, org):
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    t = create_ticket(org, "Bad status")
    resp = client_local.post(
        f"{p}/tickets/{t.id}/promote", {"area_id": area.id, "status": "blocked"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    # status is validated before anything mutates, so a bad status leaves the
    # ticket un-promoted rather than half-applied.
    t.refresh_from_db()
    assert not Slice.objects.filter(ticket=t).exists() and t.status == "open"

@pytest.mark.django_db
def test_ticket_row_has_no_manual_caret_and_area_placeholder(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    p = f"/{org.slug}"
    create_ticket(org, "Uncategorized item")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert "</select>▾" not in body          # manual caret removed
    assert "Assign area" in body           # placeholder present

@pytest.mark.django_db
def test_ticket_promote_status_only_keeps_area(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    t = create_ticket(org, "Status only change")
    resp = client_local.post(f"{p}/tickets/{t.id}/promote", {"area_id": area.id, "status": "planned"})
    assert resp.status_code in (200, 204)
    t.refresh_from_db()
    assert t.slice.area_id == area.id and t.slice.status == "planned"

@pytest.mark.django_db
def test_ticket_promote_foreign_area_404s(client_local, org):
    p = f"/{org.slug}"
    t = create_ticket(org, "To another workspace")
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    foreign_area = create_area(other_org, "Foreign")
    resp = client_local.post(
        f"{p}/tickets/{t.id}/promote", {"area_id": foreign_area.id, "status": "planned"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404
    t.refresh_from_db()
    assert not Slice.objects.filter(ticket=t).exists() and t.status == "open"

@pytest.mark.django_db
def test_inbox_heading_and_agent_source_badge(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    p = f"/{org.slug}"
    create_ticket(org, "Made by agent", source="agent")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert '<h1 class="page-title">Inbox</h1>' in body       # renamed heading
    assert 'class="source-badge is-agent"' in body           # agent item flagged

@pytest.mark.django_db
def test_ticket_dismiss_leaves_inbox_and_refreshes_count(client_local, org):
    p = f"/{org.slug}"
    t = create_ticket(org, "Not doing this")
    create_ticket(org, "Keeping this")
    resp = client_local.post(f"{p}/tickets/{t.id}/dismiss", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    t.refresh_from_db()
    assert t.status == "dismissed" and t.resolved_at is not None
    body = resp.content.decode()
    # OOB list without the dismissed row, OOB count, and a toast
    assert 'id="triage-list"' in body and "Not doing this" not in body
    assert "Keeping this" in body
    assert 'id="triage-count"' in body and ">1<" in body
    assert "Dismissed." in body

@pytest.mark.django_db
def test_dismissing_the_last_ticket_restores_the_empty_state(client_local, org):
    p = f"/{org.slug}"
    t = create_ticket(org, "Only one")
    body = client_local.post(f"{p}/tickets/{t.id}/dismiss", HTTP_HX_REQUEST="true").content.decode()
    assert 'id="triage-empty"' in body

@pytest.mark.django_db
def test_dismissed_tickets_are_reviewable_and_restorable(client_local, org):
    """A dismissal must not be a one-way door — the whole point of splitting
    'decided against' out of the old `closed`."""
    p = f"/{org.slug}"
    t = create_ticket(org, "Changed my mind")
    client_local.post(f"{p}/tickets/{t.id}/dismiss", HTTP_HX_REQUEST="true")

    inbox = client_local.get(f"{p}/inbox/").content.decode()
    assert "Changed my mind" not in inbox          # gone from the Inbox
    assert "1 dismissed" in inbox                   # but the door is visible

    review = client_local.get(f"{p}/inbox/?status=dismissed").content.decode()
    assert "Changed my mind" in review
    assert "Restore" in review
    assert "Assign area" not in review              # review list is read-only

    resp = client_local.post(f"{p}/tickets/{t.id}/reopen", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    t.refresh_from_db()
    assert t.status == "open" and t.resolved_at is None
    # restoring from the dismissed view re-renders THAT list, not the open one
    assert "Changed my mind" not in resp.content.decode()
    assert "Changed my mind" in client_local.get(f"{p}/inbox/").content.decode()

@pytest.mark.django_db
def test_promoted_ticket_cannot_be_reopened(client_local, org):
    """Reopen is a triage undo, not a demote — a slice already owns the work."""
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    t = create_ticket(org, "Already building", area=area)
    client_local.post(f"{p}/tickets/{t.id}/promote", {"area_id": area.id, "status": "planned"},
                      HTTP_HX_REQUEST="true")
    resp = client_local.post(f"{p}/tickets/{t.id}/reopen", HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    t.refresh_from_db()
    assert t.status == "promoted"

@pytest.mark.django_db
def test_promote_refreshes_the_sidebar_count(client_local, org):
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    t = create_ticket(org, "To promote")
    resp = client_local.post(f"{p}/tickets/{t.id}/promote", {"area_id": area.id, "status": "planned"},
                             HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert 'id="triage-count"' in body      # count followed the row out of the inbox
    assert "To promote" not in body

@pytest.mark.django_db
def test_bogus_status_filter_falls_back_to_the_inbox(client_local, org):
    p = f"/{org.slug}"
    create_ticket(org, "Open item")
    body = client_local.get(f"{p}/inbox/?status=nonsense").content.decode()
    assert "Open item" in body
    assert '<h1 class="page-title">Inbox</h1>' in body

@pytest.mark.django_db
def test_dismiss_refreshes_the_page_head_not_just_the_sidebar(client_local, org):
    """Two counts are on screen at once; leaving the header stale makes the page
    contradict itself (sidebar 3, heading 4)."""
    p = f"/{org.slug}"
    t = create_ticket(org, "Going away")
    create_ticket(org, "Staying")
    body = client_local.post(f"{p}/tickets/{t.id}/dismiss", HTTP_HX_REQUEST="true").content.decode()
    assert 'id="inbox-head-count"' in body          # page heading count
    assert 'id="triage-count"' in body              # sidebar badge
    assert 'id="inbox-dismissed-link"' in body      # and the review-surface link
    assert "1 dismissed" in body

@pytest.mark.django_db
def test_inbox_head_targets_exist_even_when_empty(client_local, org):
    """OOB targets must be on the page before the first dismissal, or the swap
    has nowhere to land."""
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert 'id="inbox-head-count"' in body
    assert 'id="inbox-dismissed-link"' in body
    assert "dismissed →" not in body                # present but empty
