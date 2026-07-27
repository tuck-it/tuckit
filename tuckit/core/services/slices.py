from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from tuckit.core.models import Area, Org, Slice
from tuckit.core.services.activity import record_activity, status_verb
from tuckit.core.services.bites import bite_progress
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.tags import get_or_create_tags
from tuckit.core.services.validation import validate_choice


def list_slices(area: Area, status: str | None = None, tag: str | None = None) -> QuerySet:
    # select_related("org") so {% ref_of %} on every row doesn't fire its own
    # SELECT against core_org — this feeds the area board's flat-list views.
    qs = Slice.objects.filter(area=area).select_related("org")
    if status:
        qs = qs.filter(status=status)
    if tag:
        qs = qs.filter(tags__name=tag)
    return qs


def query_slices(org, *, area=None, status=None, tag=None, query=None,
                 assignee_member=None, limit=None) -> list[Slice]:
    """Org-wide slice query used by the MCP list_slices tool. All filters optional;
    with no `area` it searches the whole org. `query` = icontains on title/spec."""
    # Annotated here so list_slices can report each row's stage without two
    # queries per row. Must precede the .distinct() and the slice below —
    # annotating an already-sliced queryset raises.
    qs = annotate_stage_counts(
        Slice.objects.filter(org=org).select_related("area", "assignee__user", "org")
    )
    if area is not None:
        qs = qs.filter(area=area)
    if status:
        qs = qs.filter(status=status)
    if tag:
        qs = qs.filter(tags__name=tag)
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(spec__icontains=query))
    if assignee_member is not None:
        qs = qs.filter(assignee=assignee_member)
    # order_by is explicit because the stage annotation adds a GROUP BY, and
    # Django does not apply Meta.ordering to aggregate queries — without this the
    # rank order silently disappears and the board comes back in table order.
    qs = qs.prefetch_related("tags").distinct().order_by("rank")
    if limit:
        qs = qs[:limit]
    return list(qs)


STATUS_ORDER = ["open", "shipped", "dropped"]


def grouped_slices(area: Area) -> list[tuple[str, list[Slice]]]:
    """Slices of an area grouped by status in canonical order:
    list of (status, [slices]) tuples. Tags are prefetched."""
    slices = list(list_slices(area).prefetch_related("tags"))
    return [(s, [x for x in slices if x.status == s]) for s in STATUS_ORDER]


def allocate_number(org: Org) -> int:
    """Atomically mint the next per-org number (shared by Slices and Tickets)."""
    locked = Org.objects.select_for_update().get(pk=org.pk)
    number = locked.next_slice_number
    locked.next_slice_number = number + 1
    locked.save(update_fields=["next_slice_number"])
    return number


def create_slice(
    area: Area,
    title: str,
    *,
    spec: str = "",
    status: str = "open",
    tags: list[str] | None = None,
    before: Slice | None = None,
    after: Slice | None = None,
    source: str = "human",
    assignee_member=None,
    external_key: str = "",
    number: int | None = None,
) -> Slice:
    if external_key:
        existing = Slice.objects.filter(area__org=area.org, external_key=external_key).first()
        if existing is not None:
            # Idempotent: a re-run with the same key updates in place, no duplicate.
            # Status is deliberately NOT touched here — create defaults to 'open' and
            # would otherwise regress a slice that already progressed; use update_slice
            # to move status. Empty spec is treated as "unchanged" (spec or None).
            return update_slice(
                existing, title=title, spec=spec or None, tags=tags,
                assignee=(1 if assignee_member is not None else None),
                assignee_member=assignee_member, actor=source,
            )
    validate_choice(status, Slice.STATUS_CHOICES, "status")
    rank = rank_for(Slice, {"area": area}, before=before, after=after)
    with transaction.atomic():
        if number is None:
            number = allocate_number(area.org)
        slice_ = Slice.objects.create(
            area=area,
            org=area.org,
            title=title,
            spec=spec,
            status=status,
            rank=rank,
            source=source,
            number=number,
            external_key=external_key,
            assignee=assignee_member,
            completed_at=timezone.now() if status == "shipped" else None,
        )
        if tags:
            slice_.tags.set(get_or_create_tags(area.org, tags))
        record_activity(area.org, actor=source, verb="created", target=slice_)
    return slice_


def update_slice(
    slice_: Slice,
    *,
    title: str | None = None,
    spec: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    assignee=None,
    assignee_member=None,
    before: Slice | None = None,
    after: Slice | None = None,
    actor: str = "human",
) -> Slice:
    """Update a slice. `status` folds in the old set_slice_status; before/after fold
    in reorder. `assignee` is a presence flag (non-None means "set assignee") and
    `assignee_member` is the already-resolved OrgMember (or None to clear) — the
    caller resolves the email/'me' spec so this service stays request-context-free."""
    old_status = slice_.status
    if title is not None:
        slice_.title = title
    if spec is not None:
        slice_.spec = spec
    if status is not None:
        validate_choice(status, Slice.STATUS_CHOICES, "status")
        _apply_status(slice_, status)
    if assignee is not None:
        slice_.assignee = assignee_member
    if before is not None or after is not None:
        slice_.rank = rank_for(Slice, {"area": slice_.area}, before=before, after=after)
    with transaction.atomic():
        slice_.save()
        if tags is not None:
            slice_.tags.set(get_or_create_tags(slice_.org, tags))
        if status is not None and status != old_status:
            record_activity(
                slice_.org, actor=actor, verb=status_verb(status),
                target=slice_, from_value=old_status, to_value=status,
            )
    return slice_


def _apply_status(slice_: Slice, status: str) -> None:
    slice_.status = status
    if status == "shipped":
        slice_.completed_at = slice_.completed_at or timezone.now()
    else:
        slice_.completed_at = None


# NOTE: a Slice's status is deliberately NOT mirrored back onto its originating
# Ticket. The Ticket's lifecycle ends at promotion; "is it delivered yet" is read
# from the Slice (`ticket.slice.status`). Copying it would drift the moment a
# shipped slice is reopened — which is exactly what the old _autoclose_ticket did.


def set_slice_status(slice_: Slice, status: str, *, actor: str = "human") -> Slice:
    validate_choice(status, Slice.STATUS_CHOICES, "status")
    old_status = slice_.status
    _apply_status(slice_, status)
    with transaction.atomic():
        slice_.save(update_fields=["status", "completed_at", "updated_at"])
        if status != old_status:
            record_activity(
                slice_.org, actor=actor, verb=status_verb(status),
                target=slice_, from_value=old_status, to_value=status,
            )
    return slice_


def reorder_slice(slice_: Slice, *, before: Slice | None = None, after: Slice | None = None) -> Slice:
    slice_.rank = rank_for(Slice, {"area": slice_.area}, before=before, after=after)
    slice_.save(update_fields=["rank", "updated_at"])
    return slice_


def set_slice_area(
    slice_: Slice, area: Area, *, before: Slice | None = None, after: Slice | None = None,
    actor: str = "human",
) -> Slice:
    old_area = slice_.area
    if area.org_id != old_area.org_id:
        raise InvalidValue("cannot move a slice across orgs")
    slice_.area = area
    slice_.rank = rank_for(Slice, {"area": area}, before=before, after=after)
    with transaction.atomic():
        slice_.save(update_fields=["area", "rank", "updated_at"])
        if area.id != old_area.id:  # no spurious event when the area didn't change (e.g. concurrent resubmit)
            record_activity(
                area.org, actor=actor, verb="moved",
                target=slice_, from_value=old_area.name, to_value=area.name,
            )
    return slice_


# Workflow order: what a slice needs next, from undesigned to done. Derived on
# read and never stored — a column would need updating on every spec edit and
# bite transition, and would be wrong the first time anything wrote around it.
SLICE_STAGES = (
    "needs_design", "needs_steps", "executing", "ready_to_ship",
    "shipped", "dropped",
)

# Board columns for the stage pipeline. The board groups by derived stage, not
# stored status. dropped is not a column — the page surfaces it as a header
# count.
BOARD_STAGE_COLUMNS = ("needs_design", "needs_steps", "executing", "ready_to_ship", "shipped")


def stage_column(stage: str) -> str | None:
    """The board column a derived stage belongs to, or None if it is not a
    column (dropped). There is no folding left to do — derived stage and board
    column are 1:1."""
    return stage if stage in BOARD_STAGE_COLUMNS else None


def slice_stage(status: str, spec: str, bites_done: int, bites_total: int) -> str:
    """What to do next on this slice.

    Pure: every argument is a primitive, so the rules can be tested without a
    database. `bites_done`/`bites_total` must carry bite_progress() semantics —
    dropped bites excluded from both — or a slice whose last outstanding step
    was dropped never leaves 'executing'.

    The Plan layer is gone, so needs_plan/needs_bites collapse into a single
    needs_steps — the board has drawn them as one column since v0.35.0."""
    if status in ("shipped", "dropped"):
        # A finished slice has no next step. Deriving anyway would tell you to
        # brainstorm something already deployed.
        return status
    if not spec:
        return "needs_design"
    if bites_total == 0:
        return "needs_steps"
    if bites_done < bites_total:
        return "executing"
    return "ready_to_ship"


def stage_counts(slice_) -> tuple[int, int]:
    """(bites_done, bites_total) for one slice — reuses bite_progress() so the
    dropped-bite exclusion is stated once on the Python side."""
    return bite_progress(slice_)


def annotate_stage_counts(qs):
    """The same two numbers, computed in the database, so a list of slices
    costs no extra queries.

    Bites hang directly off the Slice now, so the nested plans__bites join is
    gone. distinct=True stays on every Count regardless — other multi-valued
    joins (tags) can still be present on the same queryset, and without it
    they would fan the rows out and multiply the counts. The failure is
    silent — the numbers stay plausible."""
    return qs.annotate(
        _bites_total=Count("bites", distinct=True, filter=~Q(bites__status="dropped")),
        _bites_done=Count("bites", distinct=True, filter=Q(bites__status="done")),
    )


def stage_of(slice_) -> str:
    """Stage for one slice. Uses annotate_stage_counts() output when present so
    list callers pay nothing, and falls back to querying for a bare instance."""
    if hasattr(slice_, "_bites_total"):
        counts = (slice_._bites_done, slice_._bites_total)
    else:
        counts = stage_counts(slice_)
    return slice_stage(slice_.status, slice_.spec, *counts)
