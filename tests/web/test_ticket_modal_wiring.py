"""Guards for the ticket modal's structure and Alpine/htmx wiring.

These assert on rendered HTML rather than on responses, because the failures
they cover are invisible to endpoint tests: an htmx attribute cannot read Alpine
state at all, so a dynamic hx-post would post to the wrong place while every
endpoint stayed green.

test_triage_area_select_declares_its_own_hx_swap below is the companion
hx-swap-inheritance guard (it used to live in the now-deleted
test_capture_triage.py, which predated this file).
"""
import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.tickets import create_ticket, promote_ticket, resolve_ticket


def _modal(client_local, org, ticket):
    return client_local.get(f"/{org.slug}/tickets/{ticket.id}/").content.decode()


@pytest.mark.django_db
def test_triage_form_posts_to_the_triage_endpoint(client_local, org):
    create_area(org, "Backend")
    t = create_ticket(org, "Open one")
    html = _modal(client_local, org, t)
    assert f"/tickets/{t.id}/triage" in html
    # The split endpoints must be gone from this surface.
    assert f"/tickets/{t.id}/merge" not in html
    assert f"/tickets/{t.id}/promote" not in html


@pytest.mark.django_db
def test_no_htmx_attribute_is_alpine_bound(client_local, org):
    # ":hx-post" and friends look like they work and never do — htmx attributes
    # are evaluated outside Alpine's scope. Alpine may drive the button label,
    # never the request target.
    create_area(org, "Backend")
    html = _modal(client_local, org, create_ticket(org, "Open one"))
    for attr in (":hx-post", ":hx-get", ":hx-vals", ":hx-confirm", ":hx-target", ":hx-swap"):
        assert attr not in html


@pytest.mark.django_db
def test_open_ticket_shows_the_meta_line_and_the_triage_row(client_local, org):
    create_area(org, "Backend")
    html = _modal(client_local, org, create_ticket(org, "Open one"))
    assert "detail-meta" in html
    assert "status-dot--open" in html
    assert "triage-row" in html
    assert "Send to" in html
    # The head badges moved down into the meta line; they must not be in both.
    assert "source-badge" not in html


@pytest.mark.django_db
def test_slice_select_defaults_to_a_new_slice(client_local, org):
    """The second dropdown is valid before an area is chosen, so promoting costs
    no interaction with it."""
    create_area(org, "Backend")
    html = _modal(client_local, org, create_ticket(org, "Open one"))
    assert 'value="new" selected' in html


@pytest.mark.django_db
def test_promoted_ticket_shows_its_destination_and_no_triage_row(client_local, org):
    area = create_area(org, "Backend")
    t = create_ticket(org, "Parent", area=area)
    promote_ticket(t)
    t.refresh_from_db()
    html = _modal(client_local, org, t)
    assert "triage-row" not in html
    assert "detail-meta-dest" in html
    assert "Backend" in html


@pytest.mark.django_db
def test_dismissed_ticket_offers_restore(client_local, org):
    t = create_ticket(org, "Not doing it")
    resolve_ticket(t, "dismissed")
    t.refresh_from_db()
    html = _modal(client_local, org, t)
    assert "triage-row" not in html
    assert "Restore to Inbox" in html
    assert "status-dot--dismissed" in html


@pytest.mark.django_db
def test_every_ticket_state_offers_a_copy_link(client_local, org):
    """The ticket has no canonical page — web:ticket returns this partial — so
    the copy control is the only way to hand someone a readable link."""
    area = create_area(org, "Backend")
    open_t = create_ticket(org, "Open one")
    promoted = create_ticket(org, "Promoted one", area=area)
    promote_ticket(promoted)
    dismissed = create_ticket(org, "Dismissed one")
    resolve_ticket(dismissed, "dismissed")

    for t in (open_t, promoted, dismissed):
        t.refresh_from_db()
        assert "Copy link" in _modal(client_local, org, t)


@pytest.mark.django_db
def test_triage_area_select_declares_its_own_hx_swap(client_local, org):
    """htmx inherits hx-swap from ancestors, and this select lives inside a form
    carrying hx-swap="none" for its own submit. Without an explicit swap the
    options request fires, returns 200, and is silently discarded — the select
    stays empty and merging is impossible. Found in the browser; no endpoint
    test can see it, because the endpoint is fine."""
    t = create_ticket(org, "Open one", area=create_area(org, "Backend"))
    body = _modal(client_local, org, t)

    start = body.index('name="area_id"')
    select_tag = body[start:body.index(">", start)]
    assert 'hx-swap="innerHTML"' in select_tag
