"""`{# … #}` is single-line, and a multi-line one is not a comment at all.

Django renders it verbatim, so the "comment" becomes page text. It happened on
the hosted checkout page, which is not in this repo — but every template
convention this project has lives here, and there are eighty-odd templates in
core where nothing would fail if it happened again: the response is still a
200, still with the right content in it, just with a paragraph of source
commentary printed above it.
"""
import pathlib

TEMPLATES = sorted(pathlib.Path("tuckit").rglob("*.html"))


def test_there_are_templates_to_scan():
    """A scan over an empty list passes forever and proves nothing."""
    assert len(TEMPLATES) > 50


def test_no_template_opens_a_comment_it_never_closes_on_the_same_line():
    offenders = [
        f"{path}:{i}"
        for path in TEMPLATES
        for i, line in enumerate(path.read_text().splitlines(), 1)
        if "{#" in line and "#}" not in line
    ]
    assert not offenders, (
        f"multi-line {{# … #}} renders as page text; use {{% comment %}}: {offenders}"
    )
