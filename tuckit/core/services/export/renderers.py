"""The three output formats. Each reads EXPORT_SCHEMA, never the models."""
import csv as _csv
import io
import json
import zipfile
from datetime import datetime

from django.utils.text import slugify

from tuckit.core.services.export.collect import Snapshot, rows
from tuckit.core.services.export.schema import EXPORT_SCHEMA, SCHEMA_VERSION
from tuckit.core.services.state import render_slice_markdown


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


def _slice_filename(slice_) -> str:
    """'<REF>-<slug>.md', or '<REF>.md' when the title has no ASCII to slug.

    slugify() strips non-ASCII, so a Korean-only title slugs to "", and
    allow_unicode=True would instead write zip entries that break on Windows.
    The bare ref is the safe answer; the title is inside the file either way.
    """
    slug = slugify(slice_.title)[:60].strip("-")
    return f"{slice_.export_ref}-{slug}.md" if slug else f"{slice_.export_ref}.md"


def _slice_document(snapshot: Snapshot, slice_) -> str:
    area = slice_.area.name if slice_.area_id else "Inbox"
    assignee = slice_.assignee.user.email if slice_.assignee_id else "—"
    tags = " ".join(sorted(t.name for t in slice_.tags.all())) or "—"
    header = [
        f"> **{slice_.export_ref}** · {slice_.status} · {slice_.export_stage}",
        f"> Area: {area} · Assignee: {assignee} · Tags: {tags}",
        f"> Created: {slice_.created_at.date().isoformat()}"
        f" · Updated: {slice_.updated_at.date().isoformat()}",
        "",
    ]
    # bites= and activity= are passed from the snapshot: without them this
    # renderer would issue three queries per slice, which is the one place a
    # large org actually hurts.
    body = render_slice_markdown(
        slice_,
        with_activity=True,
        bites=snapshot.bites_by_slice.get(slice_.id, []),
        activity=snapshot.activity_by_slice.get(slice_.id, []),
    )
    return "\n".join(header) + body


def _readme(snapshot: Snapshot, *, exported_at) -> str:
    org = snapshot.org
    return "\n".join([
        f"# {org.name} — tuckit export",
        "",
        f"- Exported: {exported_at.isoformat()}",
        f"- Organization: {org.name} (`{org.slug}`, ref prefix `{org.key}`)",
        f"- schema_version: {SCHEMA_VERSION}",
        "",
        "## What is in here",
        "",
        f"- `areas/<slug>/` — one folder per area ({len(snapshot.areas)} total),"
        " with `_area.md` describing it",
        "- `inbox/` — slices that were never filed into an area",
        f"- `activity.md` — the full activity log ({len(snapshot.activity)} events)",
        "",
        f"{len(snapshot.slices)} slices and {len(snapshot.bites)} steps in total.",
        "",
        "## This is the readable copy, not the complete one",
        "",
        "Markdown is for reading. The lossless copy — every field, exactly as",
        "stored — is the JSON export from the same screen. If you are moving",
        "this data into another system, use that one.",
        "",
    ])


def _activity_document(snapshot: Snapshot) -> str:
    lines = [f"# Activity — {snapshot.org.name}", "", "Newest first.", ""]
    for e in snapshot.activity:
        who = e.member.user.email if e.member_id else e.source
        when = e.created_at.isoformat(timespec="seconds")
        line = f"- {when} · {who} · {e.verb} {e.target_type} “{e.target_label}”"
        if e.from_value or e.to_value:
            line += f" ({e.from_value}→{e.to_value})"
        lines.append(line)
        if e.body:
            lines += [f"      {row}" for row in e.body.splitlines()]
    return "\n".join(lines) + "\n"


def render_markdown_zip(snapshot: Snapshot, *, exported_at: datetime) -> bytes:
    """A readable file tree: one markdown file per slice, under its area."""
    slices_by_area = {}
    for s in snapshot.slices:
        slices_by_area.setdefault(s.area_id, []).append(s)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", _readme(snapshot, exported_at=exported_at))
        for area in snapshot.areas:
            base = f"areas/{area.slug}"
            zf.writestr(f"{base}/_area.md",
                        f"# {area.name}\n\n{area.description}\n")
            for s in slices_by_area.get(area.id, []):
                zf.writestr(f"{base}/{_slice_filename(s)}",
                            _slice_document(snapshot, s))
        for s in slices_by_area.get(None, []):
            zf.writestr(f"inbox/{_slice_filename(s)}",
                        _slice_document(snapshot, s))
        if snapshot.activity:
            zf.writestr("activity.md", _activity_document(snapshot))
    return buf.getvalue()
