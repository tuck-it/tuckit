"""The overlay layer: one base class, one container, one close path.

These are template-level assertions on purpose. The bugs this area produces
(a modal stacking under the onboarding widget, an overlay with no z-index)
are invisible to endpoint tests, so the markup contract is what we pin.
"""

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
        "templates/web/partials/_area_header.html",
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
    s = create_slice(a, "Payment integration")
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
    s = create_slice(a, "Payment integration")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    # Only <main>. The skeleton <template> further down the page legitimately
    # contains .detail-card markup that is never rendered.
    main = body.split('id="main-content"', 1)[1].split("</main>", 1)[0]
    assert 'data-url-param="slice"' not in main
    assert "detail-card" not in main
    assert "detail-body" in main, "sanity: the slice partial did render here"


@pytest.mark.django_db
def test_ticket_modal_card_declares_its_dialog_contract(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    t = create_ticket(org, "Something broke")
    body = client_local.get(f"/{org.slug}/tickets/{t.id}/").content.decode()
    assert 'data-url-param="ticket"' in body
    assert 'aria-labelledby="detail-title"' in body
    assert "detail-card" in body


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
