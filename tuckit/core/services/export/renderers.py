"""The three output formats. Each reads EXPORT_SCHEMA, never the models."""
import csv as _csv
import io
import json
from datetime import datetime

from tuckit.core.services.export.collect import Snapshot, rows
from tuckit.core.services.export.schema import EXPORT_SCHEMA, SCHEMA_VERSION


def _envelope(snapshot: Snapshot, *, view: str, exported_at: datetime) -> dict:
    org = snapshot.org
    return {
        # No application version. pyproject's has not been bumped in ~50
        # releases (TP-118), so stamping it would write a false claim into a
        # file we are asking a customer to trust. schema_version is ours.
        "schema_version": SCHEMA_VERSION,
        "exported_at": exported_at.isoformat(),
        "view": view,
        # description belongs here rather than in a collection: the org is the
        # envelope, not a row. Leaving it out would quietly drop text a human
        # wrote, which is exactly what "lossless" must not mean.
        "org": {"slug": org.slug, "name": org.name, "key": org.key,
                "description": org.description},
    }


def render_json(snapshot: Snapshot, *, exported_at: datetime) -> bytes:
    """The canonical dump: every collection, flat, under a versioned envelope.

    Flat rather than nested because an Inbox slice has no area to nest under,
    an activity event points at slices, bites and areas alike, and a new entity
    should cost a new key rather than a re-shaped tree.
    """
    payload = {"tuckit_export": _envelope(snapshot, view="full",
                                          exported_at=exported_at)}
    for name in EXPORT_SCHEMA:
        payload[name] = rows(snapshot, name)
    # ensure_ascii=False so Korean stays readable when someone opens the file;
    # indent=2 because a human is a real reader of this artifact.
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _cell(value) -> str:
    """One schema value as a spreadsheet cell.

    None becomes an empty cell rather than the string "None", and a list of
    tags becomes space-separated words rather than Python list syntax. Anything
    else is left to str() — the csv module handles quoting, embedded newlines
    and commas.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_csv(snapshot: Snapshot) -> bytes:
    """One row per slice, carrying every field the JSON carries for a slice.

    The columns are the schema's, not a hand-picked subset: a new Slice column
    becomes a new CSV column with no edit here, under the same drift guard.

    Written as utf-8-sig. The BOM is load-bearing — Excel decodes a plain UTF-8
    CSV as the local codepage and renders Korean titles as mojibake, and this
    file exists precisely so someone can open it in Excel. Every Python-side
    test would still pass without it.
    """
    columns = list(EXPORT_SCHEMA["slices"].fields.keys())
    buf = io.StringIO(newline="")
    writer = _csv.DictWriter(buf, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in rows(snapshot, "slices"):
        writer.writerow({key: _cell(value) for key, value in row.items()})
    return buf.getvalue().encode("utf-8-sig")
