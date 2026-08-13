"""Which (view, format) pairs exist, and what each one produces.

A table rather than a lineup of endpoints: a new pair adds a row here and a
card on the settings page, never a route. TP-147's period filter arrives as an
extra argument to collect(), not as a new combination.
"""
from dataclasses import dataclass
from typing import Callable

from django.utils import timezone

from tuckit.core.models import Org
from tuckit.core.services.export.collect import collect
from tuckit.core.services.export.renderers import (
    render_csv, render_json, render_markdown_zip,
)


class UnknownExport(Exception):
    """No such (view, format). The web layer turns this into a 400."""


@dataclass(frozen=True)
class ExportFile:
    filename: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class Combination:
    view: str
    format: str
    extension: str
    media_type: str
    label: str
    blurb: str
    render: Callable


_COMBINATIONS = [
    Combination(
        view="full", format="json", extension="json",
        media_type="application/json; charset=utf-8",
        label="Everything (JSON)",
        blurb="The complete, lossless copy: every slice, step and activity "
              "event exactly as stored. Use this to back up or to move into "
              "another tool.",
        render=lambda snap, at: render_json(snap, exported_at=at),
    ),
    Combination(
        view="full", format="md", extension="zip",
        media_type="application/zip",
        label="Everything (Markdown, .zip)",
        blurb="A readable file tree with the same slices and activity, one "
              "Markdown file per slice, grouped by area. Drop it into a "
              "repository as-is — the JSON export is the field-for-field "
              "copy.",
        render=lambda snap, at: render_markdown_zip(snap, exported_at=at),
    ),
    Combination(
        view="report", format="csv", extension="csv",
        media_type="text/csv; charset=utf-8",
        label="Slice table (CSV)",
        blurb="One row per slice with every field, for a spreadsheet. Excel "
              "shortens any cell past 32,767 characters, so use the JSON "
              "export when you need the full text.",
        render=lambda snap, at: render_csv(snap),
    ),
]

COMBINATIONS = {(c.view, c.format): c for c in _COMBINATIONS}


def available_exports() -> list[Combination]:
    """What the settings page offers, in display order."""
    return list(_COMBINATIONS)


def export_org(org: Org, view: str, format: str, *, exported_at=None) -> ExportFile:
    """Build one export file. The only entry point the web layer needs.

    Raises UnknownExport for a pair that does not ship — including full x csv,
    which is deliberately absent because a spec body does not belong in a
    spreadsheet cell. Refusing loudly beats quietly handing over a different
    file than the one that was asked for.
    """
    combination = COMBINATIONS.get((view, format))
    if combination is None:
        raise UnknownExport(f"No export for view={view!r} format={format!r}")
    at = exported_at or timezone.now()
    snapshot = collect(org)
    content = combination.render(snapshot, at)
    name = f"tuckit-{org.slug}-{at.date().isoformat()}.{combination.extension}"
    return ExportFile(filename=name, media_type=combination.media_type,
                      content=content)
