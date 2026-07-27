from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from tuckit.core.models import Org, Slice, Ticket
from tuckit.core.services.activity import record_activity
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.refs import slice_ref
from tuckit.core.services.slices import allocate_number, create_slice
from tuckit.core.services.validation import validate_choice

_UNSET = object()


def _same_org(org: Org, obj, what: str) -> None:
    """Reject a cross-org reference. Every request-path caller already scopes its
    lookups by org, so this is defence in depth for admin/shell/import paths."""
    if obj is not None and obj.org_id != org.id:
        raise InvalidValue(f"{what} belongs to a different org")


def create_ticket(
    org: Org,
    title: str,
    *,
    body: str = "",
    area=None,
    source: str = "human",
    created_by=None,
    external_key: str = "",
    before: Ticket | None = None,
    after: Ticket | None = None,
) -> Ticket:
    """Capture a ticket into the Inbox. `external_key` makes agent re-runs
    idempotent: a second call with the same key returns the existing ticket
    instead of minting a duplicate (uniq_ticket_external_key_per_org backs this
    against concurrent retries, which a plain lookup cannot)."""
    _same_org(org, area, "area")
    _same_org(org, created_by, "created_by")
    if external_key:
        existing = Ticket.objects.filter(org=org, external_key=external_key).first()
        if existing is not None:
            return existing
    rank = rank_for(Ticket, {"org": org}, before=before, after=after)
    with transaction.atomic():
        number = allocate_number(org)
        ticket = Ticket.objects.create(
            org=org, area=area, title=title, body=body, source=source,
            created_by=created_by, external_key=external_key, number=number, rank=rank,
        )
        record_activity(org, actor=source, verb="created", target=ticket)
    return ticket


def ticket_queryset(
    org: Org, *, status: str | None = "open", area=None, query: str | None = None,
) -> QuerySet:
    """Lazy ticket query. Defaults to the Inbox (`status='open'`) — with the
    lifecycle ending at triage, open IS the inbox, so no slice join is needed."""
    # select_related("org") so {% ref_of %} on every Inbox/area-strip row
    # doesn't fire its own SELECT against core_org.
    qs = Ticket.objects.filter(org=org).select_related("org")
    if status:
        qs = qs.filter(status=status)
    if area is not None:
        qs = qs.filter(area=area)
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(body__icontains=query))
    return qs


def query_tickets(
    org: Org, *, status: str | None = "open", area=None,
    query: str | None = None, limit: int | None = None,
) -> list[Ticket]:
    """Materialized `ticket_queryset` — use that directly when you only need a
    count or want to defer evaluation."""
    qs = ticket_queryset(org, status=status, area=area, query=query)
    return list(qs[:limit] if limit else qs)


def update_ticket(
    ticket: Ticket, *, title: str | None = None, body: str | None = None,
    status: str | None = None, area=_UNSET,
    before: Ticket | None = None, after: Ticket | None = None,
    actor: str = "human",
) -> Ticket:
    if area is not _UNSET:
        _same_org(ticket.org, area, "area")
        ticket.area = area
    if title is not None:
        ticket.title = title
    if body is not None:
        ticket.body = body
    if before is not None or after is not None:
        ticket.rank = rank_for(Ticket, {"org": ticket.org}, before=before, after=after)
    if status is not None and status != ticket.status:
        validate_choice(status, Ticket.STATUS_CHOICES, "status")
        if status == "promoted":
            raise InvalidValue("use promote_ticket() to promote — it creates the slice")
        # _apply_status does a full save, so the field edits above ride along.
        return _apply_status(ticket, status, actor=actor)
    ticket.save()
    return ticket


def resolve_ticket(ticket: Ticket, resolution: str, *, actor: str = "human") -> Ticket:
    """End a ticket's lifecycle without promoting it: 'dismissed' (decided
    against) or 'duplicate'. A no-op on an already-resolved ticket."""
    if resolution not in ("dismissed", "duplicate"):
        raise InvalidValue(f"invalid resolution: {resolution!r}")
    if ticket.status != "open":
        return ticket
    return _apply_status(ticket, resolution, actor=actor)


def reopen_ticket(ticket: Ticket, *, actor: str = "human") -> Ticket:
    """Send a dismissed/duplicate ticket back to the Inbox — triage decisions are
    revisable. A promoted ticket is NOT reopenable: a Slice already exists and
    owns the work, so undoing that is a demote, not a reopen."""
    if ticket.status == "open":
        return ticket
    if ticket.status == "promoted":
        raise InvalidValue("a promoted ticket already has a slice — it cannot be reopened")
    return _apply_status(ticket, "open", actor=actor)


def _apply_status(ticket: Ticket, status: str, *, actor: str, to_value: str = "") -> Ticket:
    old = ticket.status
    ticket.status = status
    ticket.resolved_at = timezone.now() if status in Ticket.RESOLVED_STATUSES else None
    verb = {"promoted": "promoted", "dismissed": "dismissed",
            "duplicate": "dismissed"}.get(status, "status_changed")
    with transaction.atomic():
        ticket.save()
        record_activity(ticket.org, actor=actor, verb=verb, target=ticket,
                        from_value=old, to_value=to_value or status)
    return ticket


@transaction.atomic
def promote_ticket(ticket: Ticket, *, area=None, actor: str = "human") -> Slice:
    """Promote a Ticket into a Slice (status=open) that inherits the Ticket's
    number, so the ref survives the transition. This ENDS the Ticket's lifecycle
    (status='promoted'); from here the Slice is the source of truth for progress
    — read `ticket.slice.status`, which cannot drift.

    The Slice starts with an EMPTY spec. The body stays on the Ticket and the
    two are joined by `ticket.slice`, so there is exactly one copy of the text —
    the same argument this model already makes for status, applied to prose.

    Atomic and idempotent: the ticket row is locked for the whole promotion, so
    a retried request returns the slice the first call created rather than
    minting a second one (or leaving an orphan slice behind if the link fails)."""
    # of=("self",) locks the ticket row only. Without it Postgres rejects the
    # whole statement — `area` is nullable, so select_related emits a LEFT OUTER
    # JOIN and "FOR UPDATE cannot be applied to the nullable side of an outer
    # join". (SQLite ignores select_for_update entirely, so it hides this.)
    ticket = (
        Ticket.objects.select_for_update(of=("self",))
        .select_related("area", "org")
        .get(pk=ticket.pk)
    )
    if ticket.slice_id is not None:
        return ticket.slice
    if ticket.status != "open":
        raise InvalidValue(f"only open tickets can be promoted (status={ticket.status!r})")

    target_area = area or ticket.area
    if target_area is None:
        raise InvalidValue("Promoting a ticket needs an area")
    _same_org(ticket.org, target_area, "area")

    # spec stays empty on purpose. It is the design-doc slot, and "spec is
    # blank" is how the workflow tells that a slice has not been designed yet —
    # seeding it with the capture makes every promoted slice look designed and
    # sends the next reader straight to planning. The body stays on the Ticket
    # and is reached through the link, so there is exactly one copy of the text.
    slice_ = create_slice(
        target_area, ticket.title, spec="", status="open",
        source=actor, number=ticket.number,
    )
    ticket.slice = slice_
    # _apply_status() below does a full save(), so the FK assignment rides along
    # — no second write.
    # Record the stable ref, not the title: titles change and aren't unique.
    _apply_status(ticket, "promoted", actor=actor, to_value=slice_ref(slice_))
    return slice_


def origin_ticket(slice_) -> Ticket | None:
    """The Ticket that gave `slice_` its ref, or None for a directly-created
    slice. Derived rather than stored: promotion reuses the origin's number, and
    uniq_ticket_number_per_org means at most one linked ticket can match."""
    return slice_.tickets.filter(number=slice_.number).first()


@transaction.atomic
def absorb_ticket(ticket: Ticket, into: Slice, *, actor: str = "human") -> Ticket:
    """Fold an open Ticket into an EXISTING Slice instead of minting a new one.

    Differs from promote_ticket in exactly two ways: no Slice is created, and no
    number changes hands — the absorbed ticket keeps its own ref while the work
    moves under the slice's.

    The status becomes 'promoted' because the ticket's one question ("are we
    doing this?") is answered yes. 'duplicate' would describe a merge as a
    coincidence, which is what made hand-folding lose information."""
    if ticket.slice_id == into.pk:
        return ticket
    if ticket.status != "open":
        raise InvalidValue(f"only open tickets can be absorbed (status={ticket.status!r})")
    _same_org(ticket.org, into, "slice")
    ticket.slice = into
    # _apply_status() does a full save(), so the FK assignment rides along.
    return _apply_status(ticket, "promoted", actor=actor, to_value=slice_ref(into))


@transaction.atomic
def release_ticket(ticket: Ticket, *, actor: str = "human") -> Ticket:
    """Detach an absorbed Ticket from its Slice and return it to the Inbox.

    Absorbed tickets only. The origin gave the Slice its number, so releasing it
    would orphan the ref and block re-promotion — the Slice already occupies
    that number under uniq_slice_number_per_org. Undoing a promote means
    dropping the Slice, the same distinction reopen_ticket already draws."""
    if ticket.slice_id is None:
        return ticket
    if origin_ticket(ticket.slice) == ticket:
        raise InvalidValue("the origin ticket cannot be released — drop the slice instead")
    ticket.slice = None
    return _apply_status(ticket, "open", actor=actor)
