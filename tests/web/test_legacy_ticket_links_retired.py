"""The legacy ticket deep links are retired, not merely unused.

Two of them survived v0.44.0 as a deliberate safety net: `/<org>/tickets/<id>/`
and the `?ticket=<id>` param, both of which forwarded a bookmark to the Slice
that capture became. Neither could do that without reading the Ticket table,
and 0050 drops it — so they go together.

These are the tests that would have quietly kept passing if the routes had been
left behind: a 404 and an ignored query param look like nothing at all, which
is exactly why they are asserted rather than assumed.
"""
import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_the_ticket_route_is_gone(client_local, org):
    """It 404s now instead of forwarding. The ~27 already-published URLs carry
    a ticket id, and there is no longer anything that id names — answering
    with someone else's slice would be a guess."""
    for path in (f"/{org.slug}/tickets/1/", f"/{org.slug}/tickets/999999/"):
        assert client_local.get(path).status_code == 404, path
        assert client_local.get(path, HTTP_HX_REQUEST="true").status_code == 404, path


@pytest.mark.django_db
def test_the_ticket_param_no_longer_redirects_anywhere(client_local, org):
    """`?ticket=<id>` used to 302. With LegacyTicketLinkMiddleware gone the
    page simply renders and ignores the param — the behaviour any unrecognised
    query string has always had."""
    create_slice(org, area=create_area(org, "Backend"), title="Live work")

    for raw in ("1", "999999", "abc", "²", ""):
        resp = client_local.get(f"/{org.slug}/inbox/?ticket={raw}")
        assert resp.status_code == 200, raw
        assert "Location" not in resp, raw


@pytest.mark.django_db
def test_the_param_does_not_disturb_the_rest_of_the_query(client_local, org):
    """The old middleware rewrote the URL to strip `ticket` when it could not
    resolve one, which meant a redirect even in the miss case. Nothing rewrites
    anything now."""
    resp = client_local.get(f"/{org.slug}/areas/?ticket=1&focus=bite")

    assert resp.status_code == 200
    assert "Location" not in resp


def test_no_ticket_middleware_is_installed():
    """A settings-level guard. The middleware class could be deleted from the
    module and left listed in MIDDLEWARE — that fails on boot, which no
    request-level test in an already-booted process would ever reach."""
    from django.conf import settings

    assert not any("Ticket" in m for m in settings.MIDDLEWARE)


def test_base_html_no_longer_arms_a_ticket_modal():
    """The modal is long gone, but if base.html kept its hx-get the browser
    would still fire a request at a dead route on every page load — and no
    response-level test would notice, because it is the template, not an
    endpoint, that does it."""
    from pathlib import Path

    import tuckit.web

    html = (Path(tuckit.web.__file__).parent / "templates/web/base.html").read_text()
    assert "request.GET.ticket" not in html
    assert "web:ticket" not in html
