from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from tuckit.core.models import Area, Org, Slice
from tuckit.core.services.activity import record_activity, status_verb
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.tags import get_or_create_tags
from tuckit.core.services.validation import validate_choice


def list_slices(area: Area, status: str | None = None, tag: str | None = None) -> QuerySet:
    qs = Slice.objects.filter(area=area)
    if status:
        qs = qs.filter(status=status)
    if tag:
        qs = qs.filter(tags__name=tag)
    return qs


def query_slices(org, *, area=None, status=None, tag=None, query=None,
                 assignee_member=None, limit=None) -> list[Slice]:
    """Org-wide slice query used by the MCP list_slices tool. All filters optional;
    with no `area` it searches the whole org. `query` = icontains on title/spec."""
    qs = Slice.objects.filter(area__org=org).select_related("area", "assignee__user")
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
    qs = qs.prefetch_related("tags").distinct()
    if limit:
        qs = qs[:limit]
    return list(qs)


STATUS_ORDER = ["idea", "planned", "building", "shipped", "dropped"]


def grouped_slices(area: Area) -> list[tuple[str, list[Slice]]]:
    """Slices of an area grouped by status in canonical order:
    list of (status, [slices]) tuples. Tags are prefetched."""
    slices = list(list_slices(area).prefetch_related("tags"))
    return [(s, [x for x in slices if x.status == s]) for s in STATUS_ORDER]


def create_slice(
    area: Area,
    title: str,
    *,
    spec: str = "",
    status: str = "idea",
    tags: list[str] | None = None,
    before: Slice | None = None,
    after: Slice | None = None,
    source: str = "human",
    assignee_member=None,
    external_key: str = "",
) -> Slice:
    if external_key:
        existing = Slice.objects.filter(area__org=area.org, external_key=external_key).first()
        if existing is not None:
            # Idempotent: a re-run with the same key updates in place, no duplicate.
            # Status is deliberately NOT touched here — create defaults to 'idea' and
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
        locked = Org.objects.select_for_update().get(pk=area.org_id)
        number = locked.next_slice_number
        locked.next_slice_number = number + 1
        locked.save(update_fields=["next_slice_number"])
        slice_ = Slice.objects.create(
            area=area,
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
            slice_.tags.set(get_or_create_tags(slice_.area.org, tags))
        if status is not None and status != old_status:
            record_activity(
                slice_.area.org, actor=actor, verb=status_verb(status),
                target=slice_, from_value=old_status, to_value=status,
            )
    return slice_


def _apply_status(slice_: Slice, status: str) -> None:
    slice_.status = status
    if status == "shipped":
        slice_.completed_at = slice_.completed_at or timezone.now()
    else:
        slice_.completed_at = None


def set_slice_status(slice_: Slice, status: str, *, actor: str = "human") -> Slice:
    validate_choice(status, Slice.STATUS_CHOICES, "status")
    old_status = slice_.status
    _apply_status(slice_, status)
    with transaction.atomic():
        slice_.save(update_fields=["status", "completed_at", "updated_at"])
        if status != old_status:
            record_activity(
                slice_.area.org, actor=actor, verb=status_verb(status),
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
    slice_.area = area
    slice_.rank = rank_for(Slice, {"area": area}, before=before, after=after)
    with transaction.atomic():
        slice_.save(update_fields=["area", "rank", "updated_at"])
        if area.id != old_area.id:  # no spurious event when the area didn't change (e.g. concurrent re-triage)
            record_activity(
                area.org, actor=actor, verb="triaged" if old_area.is_triage else "moved",
                target=slice_, from_value=old_area.name, to_value=area.name,
            )
    return slice_
