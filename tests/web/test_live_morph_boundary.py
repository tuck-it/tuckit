"""The boundary between server-owned and client-owned DOM.

A live screen re-renders itself by GETting its own URL and morphing the response
over `#main-content`. Morph reconciles the live DOM *toward the server's copy* —
including attributes. That is correct for everything the server knows about
(slices, tickets, statuses) and wrong for everything it cannot know: which
overlay you have open, what you are mid-way through typing.

Alpine hides an element by writing an inline `style="display: none"` onto it at
runtime. The server's copy carries no such style, so a morph strips it and the
element becomes visible. Alpine never re-hides it, because its own reactive flag
never changed — and for the same reason Cancel/Esc are dead afterwards: setting
`modal = false` when it is already `false` is not a change, so nothing re-renders.
The overlay pops open on an agent's write and cannot be closed without a reload.

Hence the invariant guarded here:

    On a live-refresh screen, nothing inside `#main-content` may use `x-show`.

Client-owned UI belongs outside the morph target — which is where `#detail-modal`,
quick capture, the command palette and the onboarding widget already live. These
three overlays were the ones that had drifted inside it.

No endpoint test can catch this by asserting on status codes: every one of these
pages renders fine and returns 200 while the bug is present. The evidence is
structural, so the assertion is structural.
"""

import re

import pytest
from django.urls import reverse

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice

MAIN_OPEN = re.compile(r"<main\b[^>]*id=\"main-content\"", re.I)


def main_region(html):
    """The `<main id="main-content">…</main>` substring — the morph target.

    <main> cannot nest, so the first `</main>` after the opening tag closes it.
    """
    open_match = MAIN_OPEN.search(html)
    assert open_match, "no <main id=\"main-content\"> in this page"
    close = html.index("</main>", open_match.end())
    return html[open_match.start() : close]


def is_live_screen(html):
    return 'data-live-refresh="1"' in main_region(html)


def assert_no_alpine_visibility_toggles(html, screen):
    """`x-show` inside the morph target is the defect, not a style preference."""
    assert is_live_screen(html), f"{screen} is no longer a live screen — retarget this test"
    offenders = re.findall(r"x-show=\"([^\"]*)\"", main_region(html))
    assert offenders == [], (
        f"{screen}: {len(offenders)} element(s) use x-show inside #main-content: "
        f"{offenders}. A live refresh morphs this subtree toward the server's "
        f"copy and will strip Alpine's inline display:none, popping them open "
        f"with no way to close them. Move them into {{% block overlays %}}."
    )


@pytest.fixture
def populated(org):
    """An org with something on every screen, so no page is empty by accident.

    An empty page renders no overlays and would pass this test vacuously.
    """
    area = create_area(org, "Backend")
    create_slice(area, "Retry failed webhooks")
    return org, area


@pytest.mark.django_db
def test_home_keeps_the_morph_target_free_of_alpine_visibility(client_local, populated):
    org, _ = populated
    html = client_local.get(reverse("web:home", args=[org.slug])).content.decode()
    assert_no_alpine_visibility_toggles(html, "home")


@pytest.mark.django_db
def test_inbox_keeps_the_morph_target_free_of_alpine_visibility(client_local, populated):
    org, _ = populated
    html = client_local.get(reverse("web:inbox", args=[org.slug])).content.decode()
    assert_no_alpine_visibility_toggles(html, "inbox")


@pytest.mark.django_db
def test_roadmap_keeps_the_morph_target_free_of_alpine_visibility(client_local, populated):
    org, _ = populated
    html = client_local.get(reverse("web:roadmap", args=[org.slug])).content.decode()
    assert_no_alpine_visibility_toggles(html, "roadmap")


@pytest.mark.django_db
def test_areas_keeps_the_morph_target_free_of_alpine_visibility(client_local, populated):
    """The populated branch: the header's Create Area trigger."""
    org, _ = populated
    html = client_local.get(reverse("web:areas", args=[org.slug])).content.decode()
    assert_no_alpine_visibility_toggles(html, "areas (populated)")


@pytest.mark.django_db
def test_empty_areas_keeps_the_morph_target_free_of_alpine_visibility(client_local, org):
    """The empty-state branch renders a *second*, differently-placed trigger.

    Covered separately because the two branches are mutually exclusive: a fix
    applied to only one of them would still pass the populated case.
    """
    html = client_local.get(reverse("web:areas", args=[org.slug])).content.decode()
    assert "areas-empty" in html, "this org was supposed to have no areas"
    assert_no_alpine_visibility_toggles(html, "areas (empty)")


@pytest.mark.django_db
def test_area_keeps_the_morph_target_free_of_alpine_visibility(client_local, populated):
    """The worst case: Create Slice *and* Edit Area both sat inside the target."""
    org, area = populated
    html = client_local.get(reverse("web:area", args=[org.slug, area.slug])).content.decode()
    assert_no_alpine_visibility_toggles(html, "area")


@pytest.mark.django_db
def test_the_overlay_block_is_where_they_went(client_local, populated):
    """Moved out, not deleted.

    Without this, deleting the three overlays outright would satisfy every
    assertion above — the screens would be "clean" and the feature gone.
    """
    org, area = populated
    html = client_local.get(reverse("web:area", args=[org.slug, area.slug])).content.decode()
    close = html.index("</main>")
    after_main = html[close:]
    assert 'aria-label="Create a new Slice"' in after_main
    assert ">Edit area<" in after_main

    areas_html = client_local.get(reverse("web:areas", args=[org.slug])).content.decode()
    assert 'aria-label="Create a new Area"' in areas_html[areas_html.index("</main>") :]
