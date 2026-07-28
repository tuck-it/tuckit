"""`?ticket=<id>` — the last irreversible path in the product, closed.

Until Task 10 that param armed the old Ticket modal (base.html), and that
modal's Promote was one-way: `reopen_ticket()` refuses a promoted ticket, so a
misfire could not be walked back. No screen generates such a link any more, but
bookmarks and ~27 URLs already sent to people do — so the param now 302s to the
Slice that capture became instead of resurrecting the modal.

The mapping exists because 0045 folded every ticket into a slice: a promoted
ticket carries `ticket.slice`, and an untriaged one became a NEW slice that
inherited its `number`. The Ticket table is alive until 0047, so both halves of
that mapping can still be read back here.
"""
import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import create_ticket, promote_ticket


@pytest.mark.django_db
def test_promoted_ticket_deep_link_lands_on_its_slice(client_local, org):
    area = create_area(org, "Backend")
    t = create_ticket(org, "옛 캡처", area=area)
    s = promote_ticket(t, area=area)

    resp = client_local.get(f"/{org.slug}/inbox/?ticket={t.id}")

    assert resp.status_code == 302
    assert resp["Location"] == f"/{org.slug}/slices/{s.id}/"


@pytest.mark.django_db
def test_untriaged_ticket_deep_link_lands_on_the_slice_it_was_folded_into(client_local, org):
    """0045 gave the new slice the ticket's own `number`. That is the only
    thread back to a capture that was never promoted."""
    t = create_ticket(org, "정리 안 된 캡처")
    folded = create_slice(org, title="정리 안 된 캡처", number=t.number)

    resp = client_local.get(f"/{org.slug}/inbox/?ticket={t.id}")

    assert resp.status_code == 302
    assert resp["Location"] == f"/{org.slug}/slices/{folded.id}/"


@pytest.mark.django_db
def test_a_ticket_with_no_slice_at_all_just_loses_the_param(client_local, org):
    """Nothing to land on — the reader still gets the page they bookmarked
    rather than a modal that cannot be closed or a 404."""
    t = create_ticket(org, "고아")

    resp = client_local.get(f"/{org.slug}/inbox/?ticket={t.id}")

    assert resp.status_code == 302
    assert resp["Location"] == f"/{org.slug}/inbox/"
    assert client_local.get(resp["Location"]).status_code == 200


@pytest.mark.django_db
def test_the_deep_link_keeps_the_rest_of_the_query(client_local, org):
    t = create_ticket(org, "고아")

    resp = client_local.get(f"/{org.slug}/areas/?ticket={t.id}&focus=bite")

    assert resp.status_code == 302
    assert resp["Location"] == f"/{org.slug}/areas/?focus=bite"


@pytest.mark.django_db
def test_a_junk_or_foreign_ticket_param_renders_the_page(client_local, org):
    """No redirect loop and no crash: an id from another org, a deleted ticket
    or plain garbage is treated as no ticket at all. Non-numeric input is not
    even looked up — '²'.isdigit() is True, which is exactly the input that
    would raise NoReverseMatch further down."""
    from tuckit.core.models import Org

    other = Org.objects.create(name="Other", slug="other-org")
    foreign = create_ticket(other, "남의 것")

    for raw in ("²", "abc", ""):
        assert client_local.get(f"/{org.slug}/inbox/?ticket={raw}").status_code == 200
    for raw in ("999999", str(foreign.id)):
        resp = client_local.get(f"/{org.slug}/inbox/?ticket={raw}", follow=True)
        assert resp.status_code == 200
        assert resp.redirect_chain == [(f"/{org.slug}/inbox/", 302)]


@pytest.mark.django_db
def test_the_ticket_route_itself_redirects_to_the_slice(client_local, org):
    """`/tickets/<id>/` used to return the modal partial. It now sends the
    reader to the slice — including from htmx, where a bare 302 would splice a
    whole page into the overlay."""
    area = create_area(org, "Backend")
    t = create_ticket(org, "옛 캡처", area=area)
    s = promote_ticket(t, area=area)

    plain = client_local.get(f"/{org.slug}/tickets/{t.id}/")
    assert plain.status_code == 302
    assert plain["Location"] == f"/{org.slug}/slices/{s.id}/"

    hx = client_local.get(f"/{org.slug}/tickets/{t.id}/", HTTP_HX_REQUEST="true")
    assert hx["HX-Redirect"] == f"/{org.slug}/slices/{s.id}/"


@pytest.mark.django_db
def test_every_one_way_ticket_route_is_gone(client_local, org):
    """promote/triage was the one action in the product that could not be
    undone. Deleting the modal without deleting its endpoints would leave it
    reachable by a hand-made POST."""
    t = create_ticket(org, "옛 캡처")
    for path in (f"tickets/{t.id}/triage", f"tickets/{t.id}/dismiss",
                 f"tickets/{t.id}/reopen", f"tickets/{t.id}/release",
                 f"tickets/{t.id}/edit", "tickets/slice-options"):
        assert client_local.post(f"/{org.slug}/{path}").status_code == 404, path


def test_base_html_no_longer_arms_a_ticket_modal():
    """The deep link is resolved on the server now. If base.html kept its
    hx-get the old modal would still open — and no response-level test would
    notice, because the endpoint it calls is fine."""
    from pathlib import Path

    import tuckit.web

    html = (Path(tuckit.web.__file__).parent / "templates/web/base.html").read_text()
    assert "request.GET.ticket" not in html
    assert "web:ticket" not in html
