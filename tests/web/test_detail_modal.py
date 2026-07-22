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
