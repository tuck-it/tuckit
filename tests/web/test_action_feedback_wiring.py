"""Guards for the four modal/feedback defects found by browser verification
(TP-61, TP-62, TP-70, TP-71).

Two kinds of test live here and they are NOT equally strong:

* The response tests below assert real server behaviour — fragment ORDER and a
  response header — and would fail if the fix were reverted.
* The `_wiring` tests read the shipped JS and assert a guard is present. They
  prove the code is wired, not that the browser behaves. Both defects they
  cover (a skeleton painted over an open modal, a scrim left behind after an
  OOB empty) are invisible to endpoint tests by construction: the responses
  were already correct in both cases, only the client differed. The real
  evidence is the browser session recorded on TP-69; these keep the fix from
  being deleted by someone who cannot reproduce it.
"""

from pathlib import Path

import pytest

import tuckit.web
from tuckit.core.services.activity import latest_activity_id
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


def _base_html():
    return (Path(tuckit.web.__file__).parent / "templates/web/base.html").read_text()


def _live_js():
    return (Path(tuckit.web.__file__).parent / "static/web/live.js").read_text()


# --------------------------------------------------------------------------
# TP-70: the OOB bundle's order decides whether the toast survives
# --------------------------------------------------------------------------
# `.detail-body` is replaced wholesale, and the control that fired the request
# (the area menu, Move to Inbox, Ship/Drop) sits inside it. Swap it first and
# htmx loses the requesting element before it reaches the rest of the bundle,
# so the toast, the sidebar count and the Inbox list are dropped: the action
# lands, the panel grows, and the user is told nothing and offered no Undo.


@pytest.mark.django_db
def test_area_change_from_panel_puts_the_toast_before_the_panel(client_local, org):
    a, b = create_area(org, "Alpha"), create_area(org, "Beta")
    s = create_slice(org, area=a, title="x", spec="designed")
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/area",
        {"area_id": b.id, "from": "detail"},
        HTTP_HX_REQUEST="true",
    )
    body = resp.content.decode()
    assert 'id="toast"' in body
    assert "outerHTML:.detail-body" in body
    assert body.index('id="toast"') < body.index("outerHTML:.detail-body"), (
        "the panel swap destroys the requesting element — it must come last"
    )


@pytest.mark.django_db
def test_move_to_inbox_from_panel_puts_the_toast_before_the_panel(client_local, org):
    s = create_slice(org, area=create_area(org, "Alpha"), title="x", spec="designed")
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/area",
        {"area_id": "", "from": "detail"},
        HTTP_HX_REQUEST="true",
    )
    body = resp.content.decode()
    assert body.index('id="toast"') < body.index("outerHTML:.detail-body")


@pytest.mark.django_db
def test_status_undo_puts_the_toast_before_the_panel(client_local, org):
    """Only the Undo branch of a status change OOB-swaps the panel; the forward
    branch answers the button's own primary swap instead (see
    test_forward_status_response_does_not_self_target). So this is the status
    path that can lose its bundle to the destructive swap — and it is exactly
    the one where losing the toast costs a second reversal."""
    s = create_slice(org, area=create_area(org, "Alpha"), title="x", spec="designed")
    client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "dropped"})

    body = client_local.post(
        f"/{org.slug}/slices/{s.id}/status?undo_status=open"
    ).content.decode()

    assert 'hx-swap-oob="outerHTML:.detail-body"' in body
    assert body.index('id="toast"') < body.index("outerHTML:.detail-body")


@pytest.mark.django_db
def test_the_counts_still_ride_along_after_the_toast(client_local, org):
    """The bundle is not just toast+panel — the ordering fix must not have
    pushed the count/list fragments behind the destructive swap either."""
    a, b = create_area(org, "Alpha"), create_area(org, "Beta")
    s = create_slice(org, area=a, title="x", spec="designed")
    body = client_local.post(
        f"/{org.slug}/slices/{s.id}/area",
        {"area_id": b.id, "from": "detail"},
        HTTP_HX_REQUEST="true",
    ).content.decode()
    panel_at = body.index("outerHTML:.detail-body")
    for fragment in ('id="toast"', 'id="ticket-count"', 'id="inbox-list"'):
        assert fragment in body
        assert body.index(fragment) < panel_at, f"{fragment} must precede the panel swap"


# --------------------------------------------------------------------------
# TP-71: a tab must not have its own writes announced back to it
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_mutating_response_carries_the_live_cursor(client_local, org):
    s = create_slice(org, area=create_area(org, "Alpha"), title="x", spec="designed")
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/status", {"status": "shipped"}, HTTP_HX_REQUEST="true"
    )
    assert resp["X-Live-Cursor"] == str(latest_activity_id(org))


@pytest.mark.django_db
def test_the_cursor_covers_the_event_this_request_just_wrote(client_local, org):
    """Read after the view, not before: a watermark taken too early would let
    the poller re-announce the very action that produced it."""
    s = create_slice(org, area=create_area(org, "Alpha"), title="x", spec="designed")
    before = latest_activity_id(org)
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/status", {"status": "shipped"}, HTTP_HX_REQUEST="true"
    )
    assert int(resp["X-Live-Cursor"]) > before


@pytest.mark.django_db
def test_get_requests_are_not_stamped(client_local, org):
    """A page fetch writes nothing. Stamping it would let an ordinary GET
    swallow a concurrent write by another member — they would never toast."""
    resp = client_local.get(f"/{org.slug}/inbox/")
    assert resp.status_code == 200
    assert "X-Live-Cursor" not in resp


@pytest.mark.django_db
def test_non_tenant_response_is_not_stamped(client_local):
    """No request.org, no org-scoped cursor to publish."""
    assert "X-Live-Cursor" not in client_local.get("/healthcheck")


@pytest.mark.django_db
def test_deleting_the_org_does_not_500_on_the_way_out(client_local, org):
    """The view can delete the very org the request ran under, leaving
    request.org an unsaved husk (pk=None). Filtering a relation by one raises,
    and raising HERE — after the response exists — would turn a successful
    deletion into a 500."""
    resp = client_local.post(f"/{org.slug}/settings/delete")
    assert resp.status_code in (200, 302), resp.status_code
    assert "X-Live-Cursor" not in resp


def test_live_js_adopts_the_cursor_from_mutating_responses_wiring():
    js = _live_js()
    assert "X-Live-Cursor" in js, "live.js must read the watermark the server sends"
    assert "htmx:afterRequest" in js
    assert "seen > cursor" in js, "the cursor must only ever move forward"


# --------------------------------------------------------------------------
# TP-61 / TP-62: browser-only defects, wiring guards
# --------------------------------------------------------------------------


def test_skeleton_is_not_painted_for_requests_from_inside_the_modal_wiring():
    """TP-61. The deep-link container carries hx-target="#detail-modal" and htmx
    INHERITS it, so actions fired from inside an open panel arrived at the
    skeleton painter with target === the container. They answer hx-swap="none",
    so nothing ever replaced the skeleton."""
    assert "if (e.detail.elt !== t && t.contains(e.detail.elt)) return;" in _base_html()


def test_emptying_the_modal_releases_its_chrome_wiring():
    """TP-62. _capture_result.html empties #detail-modal via OOB without going
    through closeDetail(), which left body.modal-open set — and with it an empty
    full-viewport scrim that dimmed the page, blocked scrolling and ate the next
    click, with focus stranded on BODY."""
    html = _base_html()
    assert "function releaseDetailChrome()" in html
    assert "htmx:afterSettle" in html
    assert "releaseDetailChrome();" in html


def test_close_detail_still_goes_through_the_shared_chrome_release_wiring():
    """The split must not have left closeDetail() with its own divergent copy."""
    html = _base_html()
    body = html[html.index("function closeDetail()"):]
    body = body[: body.index("\n    }")]
    assert "releaseDetailChrome();" in body
    assert "classList.remove" not in body, "closeDetail must not re-implement the release"
