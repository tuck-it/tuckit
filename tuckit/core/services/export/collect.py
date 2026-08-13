"""One prefetched pass over an org, shared by every renderer.

The query count is fixed — it does not grow with the number of slices — so a
large org costs the same round trips as a small one. tests assert this rather
than trusting the reading.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from tuckit.core.models import ActivityEvent, Area, Bite, Org, OrgMember, Slice
from tuckit.core.services.export.schema import EXPORT_SCHEMA
from tuckit.core.services.refs import slice_ref
from tuckit.core.services.slices import annotate_stage_counts, stage_of


@dataclass
class Snapshot:
    org: Org
    members: list = field(default_factory=list)
    areas: list = field(default_factory=list)
    slices: list = field(default_factory=list)
    bites: list = field(default_factory=list)
    activity: list = field(default_factory=list)
    bites_by_slice: dict = field(default_factory=dict)
    activity_by_slice: dict = field(default_factory=dict)


def collect(org: Org) -> Snapshot:
    # all_objects, not objects: the default manager hides ended memberships,
    # and an export that drops the people who left silently unnames every
    # slice they authored.
    members = list(
        OrgMember.all_objects.filter(org=org).select_related("user").order_by("id")
    )
    areas = list(Area.objects.filter(org=org).order_by("rank"))

    # order_by is explicit: annotate_stage_counts() adds a GROUP BY, and Django
    # drops Meta.ordering when it does. sqlite returns rows in rowid order and
    # hides the loss; Postgres does not. distinct=True inside the annotation
    # keeps the tags prefetch from fanning rows out and doubling the counts.
    slices = list(
        annotate_stage_counts(
            Slice.objects.filter(org=org).select_related("org", "area",
                                                         "assignee__user",
                                                         "created_by__user")
        )
        .prefetch_related("tags")
        .order_by("rank")
    )

    bites = list(Bite.objects.filter(slice__org=org).order_by("slice_id", "rank"))
    activity = list(ActivityEvent.objects.filter(org=org)
                    .select_related("member__user").order_by("-created_at"))

    bites_by_slice = defaultdict(list)
    for b in bites:
        bites_by_slice[b.slice_id].append(b)

    # Group in Python off the single activity query rather than calling
    # slice_activity() per slice, which costs two queries each. A bite's events
    # belong to the thread of the slice that bite hangs on.
    slice_of_bite = {b.id: b.slice_id for b in bites}
    activity_by_slice = defaultdict(list)
    for e in activity:
        if e.target_type == "slice":
            activity_by_slice[e.target_id].append(e)
        elif e.target_type == "bite" and e.target_id in slice_of_bite:
            activity_by_slice[slice_of_bite[e.target_id]].append(e)
    for events in activity_by_slice.values():
        events.sort(key=lambda e: e.created_at)  # oldest first, like the thread

    for s in slices:
        # Attached, not stored: the schema reads flat attributes so it can stay
        # a table of extractors. stage_of() reuses the annotation, so this
        # costs no queries.
        s.export_ref = slice_ref(s)
        s.export_stage = stage_of(s)
        s.export_bites_done = s._bites_done
        s.export_bites_total = s._bites_total

    return Snapshot(
        org=org, members=members, areas=areas, slices=slices, bites=bites,
        activity=activity,
        bites_by_slice=dict(bites_by_slice),
        activity_by_slice=dict(activity_by_slice),
    )


def rows(snapshot: Snapshot, collection: str) -> list[dict]:
    """Apply the EntitySpec's extractors to one collection of the snapshot."""
    spec = EXPORT_SCHEMA[collection]
    objects = getattr(snapshot, collection)
    return [{key: get(obj) for key, get in spec.fields.items()} for obj in objects]
