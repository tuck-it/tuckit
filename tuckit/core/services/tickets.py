from django.db import transaction
from django.utils import timezone

from tuckit.core.models import Org, Ticket
from tuckit.core.services.activity import record_activity
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.slices import allocate_number, create_slice

_UNSET = object()


def create_ticket(
    org: Org,
    title: str,
    *,
    body: str = "",
    area=None,
    source: str = "human",
    created_by=None,
    before: Ticket | None = None,
    after: Ticket | None = None,
) -> Ticket:
    rank = rank_for(Ticket, {"org": org}, before=before, after=after)
    with transaction.atomic():
        number = allocate_number(org)
        ticket = Ticket.objects.create(
            org=org, area=area, title=title, body=body,
            source=source, created_by=created_by, number=number, rank=rank,
        )
        record_activity(org, actor=source, verb="created", target=ticket)
    return ticket


def query_tickets(
    org: Org, *, status: str = "open", unpromoted_only: bool = True,
    area=None, query: str | None = None, limit: int | None = None,
) -> list[Ticket]:
    """Inbox query. Defaults to open, not-yet-promoted tickets (the raw backlog)."""
    qs = Ticket.objects.filter(org=org)
    if status:
        qs = qs.filter(status=status)
    if unpromoted_only:
        qs = qs.filter(slice__isnull=True)
    if area is not None:
        qs = qs.filter(area=area)
    if query:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=query) | Q(body__icontains=query))
    if limit:
        qs = qs[:limit]
    return list(qs)


def update_ticket(
    ticket: Ticket, *, title: str | None = None, body: str | None = None,
    status: str | None = None, area=_UNSET,
    before: Ticket | None = None, after: Ticket | None = None,
    actor: str = "human",
) -> Ticket:
    if title is not None:
        ticket.title = title
    if body is not None:
        ticket.body = body
    if area is not _UNSET:
        ticket.area = area
    if before is not None or after is not None:
        ticket.rank = rank_for(Ticket, {"org": ticket.org}, before=before, after=after)
    if status is not None and status != ticket.status:
        return _apply_status(ticket, status, actor=actor, save_first=True)
    ticket.save()
    return ticket


def close_ticket(ticket: Ticket, *, actor: str = "human") -> Ticket:
    if ticket.status == "closed":
        return ticket
    return _apply_status(ticket, "closed", actor=actor)


def _apply_status(ticket: Ticket, status: str, *, actor: str, save_first: bool = False) -> Ticket:
    old = ticket.status
    ticket.status = status
    ticket.closed_at = timezone.now() if status == "closed" else None
    with transaction.atomic():
        ticket.save()
        if status != old:
            verb = "closed" if status == "closed" else "status_changed"
            record_activity(ticket.org, actor=actor, verb=verb, target=ticket,
                            from_value=old, to_value=status)
    return ticket


def promote_ticket(ticket: Ticket, *, area=None, actor: str = "human") -> "Slice":
    """Promote a Ticket into a linked Slice (status=planned) that inherits the
    Ticket's number. The Ticket stays open (tracked via the Slice) until the
    Slice ships/drops. Needs an area: the given one, or the Ticket's."""
    target_area = area or ticket.area
    if target_area is None:
        raise InvalidValue("Promoting a ticket needs an area")
    slice_ = create_slice(
        target_area, ticket.title, status="planned", source=actor,
        number=ticket.number,
    )
    slice_.ticket = ticket
    slice_.save(update_fields=["ticket"])
    record_activity(ticket.org, actor=actor, verb="promoted", target=ticket,
                    to_value=slice_.title)
    return slice_


def convert_org_backlog(org: Org) -> None:
    """One-way migration helper (see migration 0031). idea-Slices with no Plan
    become Tickets (reusing their number, spec→body); idea-Slices with a Plan are
    promoted to 'planned'. Triage Areas are demoted to normal 'General' areas."""
    from tuckit.core.models import ActivityEvent, Area, Slice

    for s in Slice.objects.filter(area__org=org, status="idea"):
        if s.plans.exists():
            s.status = "planned"
            s.save(update_fields=["status", "updated_at"])
            continue
        area = None if s.area.is_triage else s.area
        t = Ticket.objects.create(
            org=org, area=area, title=s.title, body=s.spec,
            status="open", number=s.number, source=s.source, rank=s.rank,
        )
        Ticket.objects.filter(pk=t.pk).update(created_at=s.created_at)
        ActivityEvent.objects.filter(target_type="slice", target_id=s.id).delete()
        s.delete()

    for area in Area.objects.filter(org=org, is_triage=True):
        area.is_triage = False
        if area.name == "Triage":
            area.name = "General"
        area.save(update_fields=["is_triage", "name", "updated_at"])
