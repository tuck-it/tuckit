"""HTTP-level coverage for the Ticket routes Task 9 deliberately kept alive:
ticket_triage, ticket_slice_options, ticket_release, and ticket_edit, plus the
ticket_detail deep-link and the modal-close OOB swap on ticket_dismiss.

These all still back the Area page's own "Inbox" strip (_area_inbox.html) and
the Ticket modal (_ticket_modal.html) — a separate, still-live surface Task 9
did not touch (see task-9-report.md, "Scope decision"). Tasks 10/11 retire
that surface and this file with it; until then it needs the same HTTP-level
coverage everything else in the app gets.

Migrated (with minimal adaptation for one changed response shape — see the
`ticket_edit` note below) from the now-deleted tests/web/test_capture_triage.py,
which tested this behavior back when the Inbox page itself was Ticket-based.
"""
import pytest

from tuckit.core.models.org import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import absorb_ticket, create_ticket, promote_ticket


# --- triage: one endpoint, "where does this ticket go?" ---
# slice_id == "new" mints a slice (promote); a numeric id folds into an existing
# one (absorb). These were separate endpoints behind two identical-looking
# "Choose area" selects that meant different things — one named where to build,
# the other only filtered a list. That is one decision, so it is one endpoint.


@pytest.mark.django_db
def test_ticket_triage_new_slice_promotes(client_local, org):
    p = f"/{org.slug}"
    backend = create_area(org, "Backend")
    t = create_ticket(org, "To move")

    client_local.post(f"{p}/tickets/{t.id}/triage",
                      {"area_id": backend.id, "slice_id": "new"},
                      HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert t.status == "promoted"
    assert t.slice is not None and t.slice.area_id == backend.id


@pytest.mark.django_db
def test_ticket_triage_defaults_to_a_new_slice(client_local, org):
    # A form that somehow omits slice_id must not 500 or silently merge into an
    # arbitrary slice — the safe default is the one the UI preselects.
    p = f"/{org.slug}"
    backend = create_area(org, "Backend")
    t = create_ticket(org, "No slice field")

    client_local.post(f"{p}/tickets/{t.id}/triage", {"area_id": backend.id},
                      HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert t.status == "promoted" and t.slice is not None


@pytest.mark.django_db
def test_ticket_triage_absorbs_into_the_chosen_slice(client_local, org):
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    target = promote_ticket(create_ticket(org, "Parent", area=area))
    t = create_ticket(org, "Child", area=area)

    client_local.post(f"{p}/tickets/{t.id}/triage",
                      {"area_id": area.id, "slice_id": target.id},
                      HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert t.slice_id == target.id and t.status == "promoted"


@pytest.mark.django_db
def test_ticket_triage_rejects_a_slice_outside_the_chosen_area(client_local, org):
    # The area select scopes the slice list, so a mismatch means a stale form —
    # not a legitimate cross-area merge.
    p = f"/{org.slug}"
    backend = create_area(org, "Backend")
    frontend = create_area(org, "Frontend")
    target = promote_ticket(create_ticket(org, "Parent", area=frontend))
    t = create_ticket(org, "Child")

    resp = client_local.post(f"{p}/tickets/{t.id}/triage",
                             {"area_id": backend.id, "slice_id": target.id},
                             HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert resp.status_code == 400
    assert t.slice_id is None and t.status == "open"


@pytest.mark.django_db
def test_ticket_triage_rejects_a_slice_from_another_org(client_local, org):
    p = f"/{org.slug}"
    other = Org.objects.create(name="Beta", slug="beta")
    foreign = create_slice(other, area=create_area(other, "X"), title="Foreign")
    area = create_area(org, "Backend")
    t = create_ticket(org, "Child", area=area)

    resp = client_local.post(f"{p}/tickets/{t.id}/triage",
                             {"area_id": area.id, "slice_id": foreign.id},
                             HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert resp.status_code == 404
    assert t.slice_id is None


@pytest.mark.django_db
def test_ticket_triage_without_an_area_404s(client_local, org):
    p = f"/{org.slug}"
    t = create_ticket(org, "Nowhere to go")

    resp = client_local.post(f"{p}/tickets/{t.id}/triage", {"slice_id": "new"},
                             HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert resp.status_code == 404
    assert t.status == "open"


# --- slice-options: the triage form's second (existing-slice) dropdown ---


@pytest.mark.django_db
def test_slice_options_are_scoped_to_the_chosen_area(client_local, org):
    p = f"/{org.slug}"
    backend = create_area(org, "Backend")
    frontend = create_area(org, "Frontend")
    create_slice(backend.org, area=backend, title="In backend")
    create_slice(frontend.org, area=frontend, title="In frontend")

    body = client_local.get(f"{p}/tickets/slice-options",
                            {"area_id": backend.id}).content.decode()
    assert "In backend" in body and "In frontend" not in body


@pytest.mark.django_db
def test_slice_options_always_offer_a_new_slice(client_local, org):
    # The second dropdown must be valid before an area is chosen, so the option
    # list carries "new" in every response — including the empty one.
    p = f"/{org.slug}"
    area = create_area(org, "Backend")

    empty = client_local.get(f"{p}/tickets/slice-options").content.decode()
    assert 'value="new"' in empty

    filled = client_local.get(f"{p}/tickets/slice-options",
                              {"area_id": area.id}).content.decode()
    assert 'value="new"' in filled


# --- release: undo a merge from the modal ---


@pytest.mark.django_db
def test_release_returns_an_absorbed_ticket_to_the_inbox(client_local, org):
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    target = promote_ticket(create_ticket(org, "Parent", area=area))
    t = create_ticket(org, "Child", area=area)
    absorb_ticket(t, target)

    client_local.post(f"{p}/tickets/{t.id}/release", HTTP_HX_REQUEST="true")
    t.refresh_from_db()
    assert t.slice is None and t.status == "open"


@pytest.mark.django_db
def test_releasing_the_origin_over_http_is_refused(client_local, org):
    p = f"/{org.slug}"
    origin = create_ticket(org, "Parent", area=create_area(org, "Backend"))
    promote_ticket(origin)

    resp = client_local.post(f"{p}/tickets/{origin.id}/release", HTTP_HX_REQUEST="true")
    origin.refresh_from_db()
    assert resp.status_code == 400
    assert origin.slice is not None and origin.status == "promoted"


# --- edit: autosaved title/body from the modal ---


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
    # Adapted: the pre-Task-9 response also OOB-re-rendered _ticket_list.html
    # (the old Ticket-based Inbox row) so it wouldn't show a stale title. That
    # list is gone — the Inbox no longer lists Tickets at all — so
    # ticket_edit() now returns the re-rendered modal alone. Assert on that.
    out = resp.content.decode()
    assert "Precise" in out and "Vague" not in out


@pytest.mark.django_db
def test_ticket_edit_rejects_an_empty_title(client_local, org):
    p = f"/{org.slug}"
    t = create_ticket(org, "Keep me")
    assert client_local.post(f"{p}/tickets/{t.id}/edit", {"title": "   "},
                             HTTP_HX_REQUEST="true").status_code == 400
    t.refresh_from_db()
    assert t.title == "Keep me"


# --- ticket_detail: deep-link open + modal-close OOB on a triage action ---


@pytest.mark.django_db
def test_ticket_modal_deep_link_opens_from_the_inbox_url(client_local, org):
    """?ticket=<id> is base.html's global deep-link handler, not something the
    Inbox view itself reads — it still arms the modal on load from any page,
    including the (now Slice-based) Inbox."""
    p = f"/{org.slug}"
    t = create_ticket(org, "Old capture")
    body = client_local.get(f"{p}/inbox/?ticket={t.id}").content.decode()
    assert f'hx-get="/{org.slug}/tickets/{t.id}/"' in body
    assert 'hx-trigger="load"' in body


@pytest.mark.django_db
def test_ticket_actions_close_the_modal(client_local, org):
    """Dismiss/triage/release/reopen can all be fired from inside the modal, so
    the response has to clear it — the ticket it was showing just left (or
    changed state in) the list."""
    p = f"/{org.slug}"
    t = create_ticket(org, "Going")
    out = client_local.post(f"{p}/tickets/{t.id}/dismiss", HTTP_HX_REQUEST="true").content.decode()
    assert 'hx-swap-oob="innerHTML:#detail-modal"' in out
