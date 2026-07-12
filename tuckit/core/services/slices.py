from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from tuckit.core.models import Area, Slice
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
) -> Slice:
    validate_choice(status, Slice.STATUS_CHOICES, "status")
    rank = rank_for(Slice, {"area": area}, before=before, after=after)
    with transaction.atomic():
        slice_ = Slice.objects.create(
            area=area,
            title=title,
            spec=spec,
            status=status,
            rank=rank,
            source=source,
            completed_at=timezone.now() if status == "shipped" else None,
        )
        if tags:
            slice_.tags.set(get_or_create_tags(area.workspace, tags))
        record_activity(area.workspace, actor=source, verb="created", target=slice_)
    return slice_


def update_slice(
    slice_: Slice,
    *,
    title: str | None = None,
    spec: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    actor: str = "human",
) -> Slice:
    old_status = slice_.status
    if title is not None:
        slice_.title = title
    if spec is not None:
        slice_.spec = spec
    if status is not None:
        validate_choice(status, Slice.STATUS_CHOICES, "status")
        _apply_status(slice_, status)
    with transaction.atomic():
        slice_.save()
        if tags is not None:
            slice_.tags.set(get_or_create_tags(slice_.area.workspace, tags))
        if status is not None and status != old_status:
            record_activity(
                slice_.area.workspace, actor=actor, verb=status_verb(status),
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
                slice_.area.workspace, actor=actor, verb=status_verb(status),
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
                area.workspace, actor=actor, verb="triaged" if old_area.is_triage else "moved",
                target=slice_, from_value=old_area.name, to_value=area.name,
            )
    return slice_
