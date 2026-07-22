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
    assert 'id="ticket-count"' in body
    assert ">1<" in body
    # toast
    assert 'id="toast"' in body
    assert "Captured" in body
    # The Inbox list is OOB re-rendered (id-matched, reliable) with the new row;
    # it lands only if that page is open. Three elements carry hx-swap-oob="true";
    # #toast, #ticket-count, and #ticket-list. The form is hx-swap="none", so
    # anything without hx-swap-oob would be silently dropped in the browser.
    assert 'id="ticket-list"' in body
    assert body.count('hx-swap-oob="true"') >= 3
    assert "Quick note" in body
    # list is non-empty now, so the "Triage clean" placeholder must be gone
    assert 'id="ticket-empty"' not in body

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
    t.refresh_from_db()
    assert t.slice is None and t.status == "open"

@pytest.mark.django_db
def test_ticket_row_has_no_manual_caret_and_area_placeholder(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    p = f"/{org.slug}"
    create_ticket(org, "Uncategorized item")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert "</select>▾" not in body          # manual caret removed
    assert "Choose area" in body           # placeholder present (same wording as the ticket modal)

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
    t.refresh_from_db()
    assert t.slice is None and t.status == "open"

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
    assert 'id="ticket-list"' in body and "Not doing this" not in body
    assert "Keeping this" in body
    assert 'id="ticket-count"' in body and ">1<" in body
    assert "Dismissed." in body

@pytest.mark.django_db
def test_dismissing_the_last_ticket_restores_the_empty_state(client_local, org):
    p = f"/{org.slug}"
    t = create_ticket(org, "Only one")
    body = client_local.post(f"{p}/tickets/{t.id}/dismiss", HTTP_HX_REQUEST="true").content.decode()
    assert 'id="ticket-empty"' in body

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
    assert 'id="ticket-count"' in body      # count followed the row out of the inbox
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
    assert 'id="ticket-count"' in body              # sidebar badge
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

@pytest.mark.django_db
def test_inbox_row_shows_a_body_preview_and_opens_the_modal(client_local, org):
    """Agents capture tickets with real bodies; triaging blind on a title alone
    is the gap this closes."""
    p = f"/{org.slug}"
    t = create_ticket(org, "OAuth screen is ugly", body="buttons misaligned on mobile")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert "buttons misaligned on mobile" in body          # preview on the row
    assert f"/tickets/{t.id}/" in body                     # row opens the modal

@pytest.mark.django_db
def test_ticket_modal_renders_body_and_actions(client_local, org):
    p = f"/{org.slug}"
    create_area(org, "Backend")
    t = create_ticket(org, "OAuth screen is ugly", body="## Details\n\nbuttons misaligned")
    body = client_local.get(f"{p}/tickets/{t.id}/").content.decode()
    assert "<h2>Details</h2>" in body                      # markdown rendered
    assert "buttons misaligned" in body
    assert f"/tickets/{t.id}/edit" in body                 # title/body editable
    assert f"/tickets/{t.id}/promote" in body
    assert f"/tickets/{t.id}/dismiss" in body
    assert "Backend" in body                               # area choices for promote

@pytest.mark.django_db
def test_ticket_modal_deep_link_opens_from_the_inbox_url(client_local, org):
    """Attention rows link here — ?ticket=<id> must arm the modal on load."""
    p = f"/{org.slug}"
    t = create_ticket(org, "Old capture")
    body = client_local.get(f"{p}/inbox/?ticket={t.id}").content.decode()
    assert f'hx-get="/{org.slug}/tickets/{t.id}/"' in body
    assert 'hx-trigger="load"' in body

@pytest.mark.django_db
def test_attention_row_deep_links_to_the_ticket(client_local, org):
    from datetime import timedelta
    from django.utils import timezone
    p = f"/{org.slug}"
    t = create_ticket(org, "Stale one")
    Ticket.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(days=30))
    body = client_local.get(f"{p}/attention/").content.decode()
    assert f"?ticket={t.id}" in body

@pytest.mark.django_db
def test_ticket_edit_autosaves_title_and_body(client_local, org):
    """Humans author tickets too — not just agents over MCP."""
    p = f"/{org.slug}"
    t = create_ticket(org, "Vague", body="")
    resp = client_local.post(f"{p}/tickets/{t.id}/edit",
                             {"title": "Precise", "body": "with context"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    t.refresh_from_db()
    assert t.title == "Precise" and t.body == "with context"
    # the row behind the modal is re-rendered so it cannot show the old title
    out = resp.content.decode()
    assert 'id="ticket-list"' in out and "Precise" in out and "Vague" not in out

@pytest.mark.django_db
def test_ticket_edit_rejects_an_empty_title(client_local, org):
    p = f"/{org.slug}"
    t = create_ticket(org, "Keep me")
    assert client_local.post(f"{p}/tickets/{t.id}/edit", {"title": "   "},
                             HTTP_HX_REQUEST="true").status_code == 400
    t.refresh_from_db()
    assert t.title == "Keep me"

@pytest.mark.django_db
def test_promoted_ticket_modal_reads_status_off_the_slice(client_local, org):
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    t = create_ticket(org, "Ship it", area=area)
    from tuckit.core.services.tickets import promote_ticket
    from tuckit.core.services.slices import set_slice_status
    s = promote_ticket(t)
    set_slice_status(s, "building")
    body = client_local.get(f"{p}/tickets/{t.id}/").content.decode()
    assert "Promoted → Backend · building" in body        # derived, never stored
    assert f"/tickets/{t.id}/promote" not in body         # no re-promote affordance

@pytest.mark.django_db
def test_ticket_actions_close_the_modal(client_local, org):
    """Promote/dismiss can be fired from inside the modal, so the response has
    to clear it — the ticket it was showing just left the list."""
    p = f"/{org.slug}"
    t = create_ticket(org, "Going")
    out = client_local.post(f"{p}/tickets/{t.id}/dismiss", HTTP_HX_REQUEST="true").content.decode()
    assert 'hx-swap-oob="innerHTML:#ticket-modal"' in out


# --- merge: the human path for absorb_ticket ---


@pytest.mark.django_db
def test_ticket_merge_absorbs_into_the_chosen_slice(client_local, org):
    from tuckit.core.services.tickets import promote_ticket
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    target = promote_ticket(create_ticket(org, "Parent", area=area))
    t = create_ticket(org, "Child", area=area)

    client_local.post(f"{p}/tickets/{t.id}/merge", {"slice_id": target.id},
                      HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert t.slice_id == target.id and t.status == "promoted"


@pytest.mark.django_db
def test_ticket_merge_rejects_a_slice_from_another_org(client_local, org):
    p = f"/{org.slug}"
    other = Org.objects.create(name="Beta", slug="beta")
    foreign = create_slice(create_area(other, "X"), "Foreign")
    t = create_ticket(org, "Child", area=create_area(org, "Backend"))

    resp = client_local.post(f"{p}/tickets/{t.id}/merge", {"slice_id": foreign.id},
                             HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert resp.status_code == 404
    assert t.slice_id is None


@pytest.mark.django_db
def test_slice_options_are_scoped_to_the_chosen_area(client_local, org):
    p = f"/{org.slug}"
    backend = create_area(org, "Backend")
    frontend = create_area(org, "Frontend")
    create_slice(backend, "In backend")
    create_slice(frontend, "In frontend")

    # merge_area_id, not area_id: HTMX serializes the whole form on hx-get, so
    # reusing the promote form's field name would collide.
    body = client_local.get(f"{p}/tickets/slice-options",
                            {"merge_area_id": backend.id}).content.decode()
    assert "In backend" in body and "In frontend" not in body


@pytest.mark.django_db
def test_merge_control_only_offered_on_open_tickets(client_local, org):
    from tuckit.core.services.tickets import promote_ticket
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    open_t = create_ticket(org, "Still open", area=area)
    promoted_t = create_ticket(org, "Already promoted", area=area)
    promote_ticket(promoted_t)

    assert "Merge into" in client_local.get(f"{p}/tickets/{open_t.id}/").content.decode()
    assert "Merge into" not in client_local.get(f"{p}/tickets/{promoted_t.id}/").content.decode()


# --- release: undo a merge from the modal ---


@pytest.mark.django_db
def test_release_returns_an_absorbed_ticket_to_the_inbox(client_local, org):
    from tuckit.core.services.tickets import absorb_ticket, promote_ticket
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    target = promote_ticket(create_ticket(org, "Parent", area=area))
    t = create_ticket(org, "Child", area=area)
    absorb_ticket(t, target)

    client_local.post(f"{p}/tickets/{t.id}/release", HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert t.slice is None and t.status == "open"


@pytest.mark.django_db
def test_origin_ticket_modal_offers_no_release(client_local, org):
    """release_ticket() refuses the origin, so the control would be a dead end."""
    from tuckit.core.services.tickets import absorb_ticket, promote_ticket
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    origin = create_ticket(org, "Parent", area=area)
    target = promote_ticket(origin)
    child = create_ticket(org, "Child", area=area)
    absorb_ticket(child, target)

    assert "Release to Inbox" not in client_local.get(f"{p}/tickets/{origin.id}/").content.decode()
    assert "Release to Inbox" in client_local.get(f"{p}/tickets/{child.id}/").content.decode()


@pytest.mark.django_db
def test_releasing_the_origin_over_http_is_refused(client_local, org):
    from tuckit.core.services.tickets import promote_ticket
    p = f"/{org.slug}"
    origin = create_ticket(org, "Parent", area=create_area(org, "Backend"))
    promote_ticket(origin)

    resp = client_local.post(f"{p}/tickets/{origin.id}/release", HTTP_HX_REQUEST="true")
    origin.refresh_from_db()
    assert resp.status_code == 400
    assert origin.slice is not None and origin.status == "promoted"


@pytest.mark.django_db
def test_merge_area_select_declares_its_own_hx_swap(client_local, org):
    """htmx inherits hx-swap from ancestors, and this select lives inside a form
    carrying hx-swap="none" for its own submit. Without an explicit swap the
    options request fires, returns 200, and is silently discarded — the select
    stays empty and merging is impossible. Found in the browser; no endpoint
    test can see it, because the endpoint is fine."""
    t = create_ticket(org, "Open one", area=create_area(org, "Backend"))
    body = client_local.get(f"/{org.slug}/tickets/{t.id}/").content.decode()

    start = body.index('name="merge_area_id"')
    select_tag = body[start:body.index(">", start)]
    assert 'hx-swap="innerHTML"' in select_tag


@pytest.mark.django_db
def test_inbox_row_pushes_a_ticket_deep_link(client_local, org):
    """The inbox row used to open the modal without touching the URL, so a
    refresh closed it and Back could not. Slices always deep-linked; tickets
    now do too."""
    t = create_ticket(org, "Something broke")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert f'hx-push-url="/{org.slug}/inbox/?ticket={t.id}"' in body
