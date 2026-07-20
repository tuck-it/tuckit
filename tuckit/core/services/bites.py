from django.db import transaction
from django.db.models import QuerySet

from tuckit.core.models import Bite, Plan, Slice
from tuckit.core.services.activity import record_activity, status_verb
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.validation import validate_choice


def list_bites(plan_: Plan) -> QuerySet:
    return Bite.objects.filter(plan=plan_)


def slice_bites(slice_: Slice) -> QuerySet:
    return Bite.objects.filter(plan__slice=slice_)


def create_bite(
    plan_: Plan,
    title: str,
    *,
    body: str = "",
    status: str = "todo",
    before: Bite | None = None,
    after: Bite | None = None,
    source: str = "human",
) -> Bite:
    validate_choice(status, Bite.STATUS_CHOICES, "status")
    rank = rank_for(Bite, {"plan": plan_}, before=before, after=after)
    with transaction.atomic():
        b = Bite.objects.create(
            plan=plan_, title=title, body=body, status=status, rank=rank, source=source,
        )
        record_activity(plan_.slice.area.org, actor=source, verb="created", target=b)
    return b


def add_bites(plan_: Plan, items, *, source: str = "human") -> list[Bite]:
    """Create bites in order under a plan. items: [{title, body?, status?}].
    Covers both single (a one-item list) and bulk capture."""
    made = []
    for item in items:
        made.append(create_bite(
            plan_, item["title"],
            body=item.get("body", ""), status=item.get("status", "todo"),
            source=source,
        ))
    return made


def update_bite(
    bite: Bite,
    *,
    title: str | None = None,
    body: str | None = None,
    status: str | None = None,
    before: Bite | None = None,
    after: Bite | None = None,
    actor: str = "human",
) -> Bite:
    old_status = bite.status
    if title is not None:
        bite.title = title
    if body is not None:
        bite.body = body
    if status is not None:
        validate_choice(status, Bite.STATUS_CHOICES, "status")
        bite.status = status
    if before is not None or after is not None:
        bite.rank = rank_for(Bite, {"plan": bite.plan}, before=before, after=after)
    with transaction.atomic():
        bite.save()
        if status is not None and status != old_status:
            record_activity(
                bite.plan.slice.area.org, actor=actor, verb=status_verb(status),
                target=bite, from_value=old_status, to_value=status,
            )
    return bite


def set_bite_status(bite: Bite, status: str, *, actor: str = "human") -> Bite:
    validate_choice(status, Bite.STATUS_CHOICES, "status")
    old_status = bite.status
    bite.status = status
    with transaction.atomic():
        bite.save(update_fields=["status", "updated_at"])
        if status != old_status:
            record_activity(
                bite.plan.slice.area.org, actor=actor, verb=status_verb(status),
                target=bite, from_value=old_status, to_value=status,
            )
    return bite


def reorder_bite(bite: Bite, *, before: Bite | None = None, after: Bite | None = None) -> Bite:
    bite.rank = rank_for(Bite, {"plan": bite.plan}, before=before, after=after)
    bite.save(update_fields=["rank", "updated_at"])
    return bite


def delete_bite(bite: Bite) -> None:
    bite.delete()


def bite_progress(slice_: Slice) -> tuple[int, int]:
    qs = Bite.objects.filter(plan__slice=slice_).exclude(status="dropped")
    return qs.filter(status="done").count(), qs.count()
