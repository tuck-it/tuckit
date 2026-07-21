"""Whole-tree template checks for mistakes that render as visible page text.

These exist because a multi-line `{# ... #}` shipped past a green 769-test suite
and was only caught by opening the page: Django's `{#...#}` comment is
single-line only, so a comment that wraps is emitted verbatim into the HTML.
Nothing about the response status or the assertions we normally write catches
that — only a human (or this test) looking at the output does.
"""

import re
from pathlib import Path

import pytest

TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "tuckit" / "web" / "templates"
TEMPLATES = sorted(TEMPLATE_ROOT.rglob("*.html"))


def test_templates_were_found():
    assert TEMPLATES, f"no templates under {TEMPLATE_ROOT}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: str(p.relative_to(TEMPLATE_ROOT)))
def test_no_multiline_hash_comment(path: Path):
    """`{# ... #}` must open and close on one line; use {% comment %} otherwise."""
    offenders = [
        i for i, line in enumerate(path.read_text().splitlines(), 1)
        if "{#" in line and "#}" not in line.split("{#", 1)[1]
    ]
    assert not offenders, (
        f"{path.relative_to(TEMPLATE_ROOT)} line(s) {offenders}: a `{{#` comment that "
        "does not close on the same line renders as visible text — use "
        "{% comment %}...{% endcomment %}"
    )
