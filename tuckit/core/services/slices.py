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
                 assignee_member=None, include_inbox=False, inbox_only=False,
                 limit=None) -> list[Slice]:
    """Org-wide slice query used by the MCP list_slices tool. All filters optional;
    with no `area` it searches the whole org. `query` = icontains on title/spec.

    Inbox slices (area IS NULL) are excluded by default — the board and this
    query are not where the Inbox is read from; use inbox_slices() for that, or
    pass include_inbox=True to opt back in. Asking for a specific `area`
    implies you already know inbox items can't match, so the exclusion is
    skipped rather than filtering twice.

    `inbox_only=True` inverts the split: the Inbox and nothing else, via the
    shared inbox_filter() predicate, with tag/query/assignee still applied on
    top. It is the searchable form of the same set inbox_slices() gives the
    Inbox screen — the two differ only in ordering and select_related, never in
    membership.

    Because inbox_filter() pins status='open', combining `inbox_only` with a
    `status` of anything else returns nothing: a capture that was shipped or
    dropped has LEFT the Inbox, so asking for a dropped Inbox item is asking
    for a contradiction. Those slices are still reachable — drop `inbox_only`
    and filter by status, which searches the whole org including unfiled work.
    """
    # Annotated here so list_slices can report each row's stage without two
    # queries per row. Must precede the .distinct() and the slice below —
    # annotating an already-sliced queryset raises.
    qs = annotate_stage_counts(
        Slice.objects.filter(org=org).select_related("area", "assignee__user", "org")
    )
    if inbox_only:
        qs = inbox_filter(qs)
    elif not include_inbox and area is None:
        qs = filed_slices(qs)
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
    org: Org,
    *,
    area: Area | None = None,
    title: str,
    spec: str = "",
    constraints: str = "",
    status: str = "open",
    tags: list[str] | None = None,
    before: Slice | None = None,
    after: Slice | None = None,
    source: str = "human",
    assignee_member=None,
    external_key: str = "",
    number: int | None = None,
    created_by=None,
) -> Slice:
    """Create a slice. `area` is optional — omit it (or pass None) and the
    slice lands in the Inbox, picked up by inbox_slices(). `org` is the first
    argument because a slice may have no area, so org can no longer be
    derived by dereferencing area.org."""
    if area is not None and area.org_id != org.id:
        raise InvalidValue("area belongs to a different org")
    if external_key:
        existing = Slice.objects.filter(org=org, external_key=external_key).first()
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
            number = allocate_number(org)
        slice_ = Slice.objects.create(
            area=area,
            org=org,
            title=title,
            spec=spec,
            constraints=constraints,
            status=status,
            rank=rank,
            source=source,
            number=number,
            external_key=external_key,
            assignee=assignee_member,
            created_by=created_by,
            completed_at=timezone.now() if status == "shipped" else None,
        )
        if tags:
            slice_.tags.set(get_or_create_tags(org, tags))
        record_activity(org, actor=source, verb="created", target=slice_)
    return slice_


def update_slice(
    slice_: Slice,
    *,
    title: str | None = None,
    spec: str | None = None,
    constraints: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    duplicate_of: Slice | None = None,
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
    if constraints is not None:
        slice_.constraints = constraints
    if duplicate_of is not None:
        slice_.duplicate_of = duplicate_of
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


def set_slice_area(slice_: Slice, area: Area | None, *, actor: str = "human") -> Slice:
    """File a slice into `area`, or clear it (area=None) to send it back to the
    Inbox. Both directions are fully reversible — there is no one-way "promote"
    left; triage is just picking an area, and un-triage is un-picking one."""
    if area is not None and area.org_id != slice_.org_id:
        raise InvalidValue("cannot move a slice across orgs")
    old_area = slice_.area
    same = (area.id if area else None) == (old_area.id if old_area else None)
    slice_.area = area
    slice_.rank = rank_for(Slice, {"area": area})
    with transaction.atomic():
        slice_.save(update_fields=["area", "rank", "updated_at"])
        if not same:  # no spurious event when the area didn't change (e.g. concurrent resubmit)
            record_activity(
                slice_.org, actor=actor, verb="moved", target=slice_,
                from_value=old_area.name if old_area else "Inbox",
                to_value=area.name if area else "Inbox",
            )
    return slice_


def inbox_filter(qs: QuerySet) -> QuerySet:
    """The Inbox as a predicate: no area AND still open.

    The single definition of "is this in the Inbox", and the exact mirror of
    filed_slices(). Both halves of the split now read from one place:
    inbox_slices() is this plus the screen's ordering, and
    query_slices(inbox_only=True) is this plus the search filters.

    Status is part of the definition, not an extra filter one caller happens to
    apply. Dropping the `status="open"` half here would mean an agent that
    reads `inbox.open_count` from get_project_state() and then lists the Inbox
    to work through it gets two different sets the moment any unfiled capture
    was shipped or dropped — the second call silently contradicting the first,
    with nothing on either surface admitting they disagree.
    """
    return qs.filter(area__isnull=True, status="open")


def inbox_slices(org: Org) -> QuerySet:
    """Untriaged captures — the sole source for the Inbox screen. A slice with
    no area IS an inbox item; there is no separate model for it any more."""
    return (
        inbox_filter(Slice.objects.filter(org=org))
        .select_related("org")
        .order_by("-created_at")
    )


def filed_slices(qs: QuerySet) -> QuerySet:
    """Exclude Inbox items (area IS NULL) from a Slice queryset.

    The single definition of "is this filed" on the queryset side, mirroring
    inbox_slices()'s predicate on the other side of the split. Every query that
    must not surface unfiled captures — the Board, the org-wide flat status
    list, Home's your_turn, and query_slices' own default — filters through
    this rather than re-spelling `area__isnull=False`. Grouping/sorting code
    downstream (e.g. `s.area.name`) depends on this: an Inbox slice has no
    area to group or sort by."""
    return qs.filter(area__isnull=False)


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
