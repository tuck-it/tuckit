"""The three output formats. Each reads EXPORT_SCHEMA, never the models."""
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
