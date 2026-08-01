"""The overlay layer: one base class, one container, one close path.

These are template-level assertions on purpose. The bugs this area produces
(a modal stacking under the onboarding widget, an overlay with no z-index)
are invisible to endpoint tests, so the markup contract is what we pin.
"""

import re
from pathlib import Path

import pytest

import tuckit.web


def _read(path):
    return (Path(tuckit.web.__file__).parent / path).read_text()


def test_every_dimming_overlay_uses_the_overlay_base_class():
    """A dimming overlay that forgets the base class also forgets z-index:60 —
    that is exactly how .capture-overlay ended up stacking under the onboarding
    widget."""
    for partial in (
        "templates/web/partials/_capture_modal.html",
        "templates/web/partials/_command_palette.html",
        "templates/web/partials/_area_create_modal.html",
        "templates/web/partials/_slice_create_modal.html",
        # Was _area_header.html until the Edit dialog was moved out of the live
        # morph target; the header is now the title block and holds no overlay.
        "templates/web/partials/_area_edit_overlay.html",
    ):
        html = _read(partial)
        assert 'class="overlay ' in html, f"{partial} has no .overlay base class"


def test_overlay_base_sets_the_stacking_context():
    css = _read("static/web/app.css")
    base = css.split(".overlay {", 1)[1].split("}", 1)[0]
    assert "z-index: 60" in base
    assert "position: fixed" in base
    assert "inset: 0" in base


def test_there_is_exactly_one_detail_overlay_container():
    html = _read("templates/web/base.html")
    assert 'id="detail-modal"' in html
    for gone in ('id="panel"', 'id="ticket-modal"', 'id="member-modal"'):
        assert gone not in html, f"{gone} still exists — the overlays are not unified"


def test_only_one_close_function_survives():
    html = _read("templates/web/base.html")
    assert "function closeDetail(" in html
    for gone in ("function closePanel(", "function closeTicketModal(",
                 "function closeMemberModal(", "function trapPanel("):
        assert gone not in html, f"{gone} still exists"


def test_no_opener_targets_a_removed_overlay():
    """A stale hx-target is the quiet failure mode: htmx cannot find the node,
    the request still returns 200, and the response is dropped on the floor."""
    root = Path(tuckit.web.__file__).parent / "templates"
    for path in root.rglob("*.html"):
        text = path.read_text()
        for gone in ('hx-target="#panel"', 'hx-target="#ticket-modal"',
                     'hx-target="#member-modal"'):
            assert gone not in text, f"{path.name} still targets {gone}"


def test_the_detail_card_is_notion_sized():
    css = _read("static/web/app.css")
    block = css.split(".detail-card {", 1)[1].split("}", 1)[0]
    assert "min(900px, 90vw)" in block
    assert "85vh" in block


def test_the_slide_over_is_gone():
    css = _read("static/web/app.css")
    assert "#panel:not(:empty)" not in css
    assert "#panel:empty" not in css


@pytest.mark.django_db
def test_slice_modal_card_declares_its_dialog_contract(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payment integration")
    body = client_local.get(
        f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true"
    ).content.decode()
    assert 'role="dialog"' in body
    assert 'aria-modal="true"' in body
    assert 'aria-labelledby="detail-title"' in body
    assert 'data-url-param="slice"' in body
    assert "detail-card" in body


@pytest.mark.django_db
def test_slice_full_page_is_not_a_dialog(client_local, org):
    """The same partial renders the standalone page; there it is page content,
    not a dialog, and must carry no card chrome."""
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payment integration")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    # Only <main>. The skeleton <template> further down the page legitimately
    # contains .detail-card markup that is never rendered.
    main = body.split('id="main-content"', 1)[1].split("</main>", 1)[0]
    assert 'data-url-param="slice"' not in main
    assert "detail-card" not in main
    assert "detail-body" in main, "sanity: the slice partial did render here"


@pytest.mark.django_db
def test_a_ticket_deep_link_no_longer_opens_a_second_card(client_local, org):
    """There is ONE detail card. `/tickets/<id>/` used to return a second one
    with its own dialog contract; it forwarded to the slice, and 0050 retired
    the route entirely. Asserted here as well as in
    test_legacy_ticket_links_retired because what matters on THIS surface is
    that no path hands the overlay a foreign card."""
    resp = client_local.get(f"/{org.slug}/tickets/1/", HTTP_HX_REQUEST="true")
    assert resp.status_code == 404


def test_skeleton_templates_exist_and_are_closable():
    """The skeleton must ship a Close control: a modal that cannot be dismissed
    while it loads is worse than a cursor spinner."""
    html = _read("templates/web/base.html")
    assert '<template id="skeleton-detail">' in html
    assert '<template id="skeleton-small">' in html
    detail = html.split('<template id="skeleton-detail">', 1)[1].split("</template>", 1)[0]
    assert "closeDetail()" in detail
    assert 'data-skeleton="1"' in detail


def test_skeleton_is_painted_before_the_request_and_cleaned_up_on_failure():
    html = _read("templates/web/base.html")
    assert "function openSkeleton(" in html
    # painted synchronously inside the click handler, not on afterSwap
    before = html.split('addEventListener("htmx:beforeRequest"', 1)[1].split("});", 1)[0]
    assert "openSkeleton(" in before
    # a failed open must not leave the skeleton sitting there forever
    after = html.split('addEventListener("htmx:afterRequest"', 1)[1].split("});", 1)[0]
    assert "[data-skeleton]" in after
    assert "closeDetail()" in after


def test_modal_openers_do_not_get_the_progress_cursor():
    """The skeleton is the feedback now. cursor:progress stays on mutation
    buttons, where it is still the only immediate signal."""
    css = _read("static/web/app.css")
    assert '[hx-target="#detail-modal"].htmx-request' in css
    assert ".htmx-request, .htmx-request * { cursor: progress; }" in css


def test_escape_only_dismisses_the_topmost_layer():
    """Quick capture / the palette / the create dialogs stack ABOVE the detail
    modal and all listen on window. Without a guard one Esc closed the dialog
    and the modal underneath it in the same keystroke (caught in the browser,
    not by any endpoint test)."""
    html = _read("templates/web/base.html")
    assert "function dialogAboveDetail(" in html
    esc = [ln for ln in html.splitlines() if "keydown.escape.window" in ln and "closeDetail" in ln]
    assert esc, "the detail modal must close on window-level Escape"
    assert "!dialogAboveDetail()" in esc[0], \
        "Escape must not reach the modal while a dialog sits on top of it"


def test_the_sticky_crumb_reaches_the_top_of_the_modal_card():
    """A sticky offset resolves against the scrollport's PADDING box. In the
    modal the card is both the scroller and the padded box, so top:0 would park
    the crumb --detail-pad BELOW the card's edge, with the rest of the document
    scrolling visibly through the gap above it. Offset by exactly that padding.

    This is the same geometry the old bottom action bar had to correct for,
    mirrored — the actions live in the crumb now. Scoped to .detail-card: on
    the full page the scrollport is the document, where pinning the row would
    only steal height from the content."""
    css = _read("static/web/app.css")
    assert "--detail-pad" in css, "the pad must be a variable the crumb can read back"
    rule = re.search(r"\.detail-card \.detail-crumb\s*\{(.*?)\}", css, re.S).group(1)
    assert re.search(r"top:\s*calc\(-1 \* var\(--detail-pad\)\)", rule)
    # ...and the row is pulled out to the card's edges, or the negative offset
    # would lift it clear off the top of the card instead of flush against it.
    assert re.search(r"margin:\s*calc\(-1 \* var\(--detail-pad\)\)", rule)


def test_history_restore_reconciles_the_modal_against_the_url():
    """htmx saves the CURRENT page to its history cache after the response
    arrives but BEFORE the swap — and openSkeleton has already painted a card
    by then, so the LIST url's snapshot carries a skeleton. Restoring it put a
    phantom grey box over the list with the background still scroll-locked.

    Found in a browser; no endpoint test can see it, because the bug lives
    entirely in what htmx stored and replayed. What we can pin is that the
    reconciliation exists and keys off the url rather than the snapshot.
    """
    html = _read("templates/web/base.html")
    assert "htmx:historyRestore" in html, "nothing reconciles a restored snapshot"
    handler = html.split("htmx:historyRestore", 1)[1].split("});", 1)[0]
    # The decision must come from the url, not from what was restored.
    assert "searchParams.has" in handler
    # Both halves of the modal state have to follow that decision.
    assert 'classList.remove("modal-open")' in handler
    assert 'classList.add("modal-open")' in handler
    assert 'innerHTML = ""' in handler


def test_close_does_not_ask_the_container_which_param_opened_it():
    """closeDetail read the param to strip off the overlay's FIRST CHILD. During
    the loading window that child is the skeleton, and neither skeleton template
    carries data-url-param — so `if (!param) return` fired and the url was never
    cleaned. Closing on the skeleton (Esc/scrim before the response lands, or the
    afterRequest failure path) cleared the modal but left ?ticket=39 in the
    address bar for good, and the next page load re-opened the modal off that
    stale param via the hx-trigger="load" deep link.

    Reproduced in a browser against prod; no endpoint test can see it, because
    the whole bug lives in a timing window on the client.
    """
    html = _read("templates/web/base.html")
    close = html.split("function closeDetail(", 1)[1].split("\n    }", 1)[0]
    assert "dataset.urlParam" not in close, \
        "closeDetail still derives the param from whatever is inside the container"
    assert "detailParams" in close, \
        "closeDetail must strip from the canonical param list instead"


@pytest.mark.django_db
def test_the_overlay_publishes_the_canonical_detail_param_list(client_local, org):
    """The list of params that mean "an overlay is open" already exists once, in
    _DETAIL_PARAMS. Hand-copying it into base.html's JS is how the two drift: add
    a third overlay kind and only one of them learns about it."""
    from tuckit.web.templatetags.web_extras import _DETAIL_PARAMS

    body = client_local.get(f"/{org.slug}/").content.decode()
    attrs = body.split('id="detail-modal"', 1)[1].split(">", 1)[0]
    assert 'data-detail-params="' in attrs, \
        "the overlay does not publish the param list the close path needs"
    rendered = attrs.split('data-detail-params="', 1)[1].split('"', 1)[0].split()
    assert rendered == list(_DETAIL_PARAMS)


@pytest.mark.django_db
def test_long_form_editors_get_the_tall_modifier(client_local, org):
    """장문을 쓰는 면(슬라이스 spec)만 .spec-edit--tall을 받는다.
    bite body / constraints는 짧게 시작하므로 받지 않는다 — 240px 빈 상자로
    열리는 것은 개선이 아니다."""
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice

    area = create_area(org, "Backend")
    s = create_slice(area.org, area=area, title="a slice")
    body = client_local.get(
        f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true"
    ).content.decode()
    assert 'class="spec-edit spec-edit--tall"' in body   # spec
    assert 'name="constraints" class="spec-edit"' in body  # not tall
