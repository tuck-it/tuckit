"""Builders for the legacy Ticket rows this release can no longer write.

Nothing in the product creates a Ticket any more: the tickets service module
went with the MCP tools that were its last caller. Production still holds them until
migration 0047 drops the table, and several read paths exist for exactly those
rows — the `?ticket=<id>` redirect, `/tickets/<id>/`, `resolve_ref()` and the
search fallback. Those paths need Ticket rows to be tested against, so the
tests build the row SHAPES here rather than keeping a write service alive that
the product itself no longer has.

Deliberately NOT a re-implementation of the deleted service: no activity
events, no external_key idempotency, no validation, no locking. These build
data, not behaviour. If a test needs behaviour from the old ticket lifecycle,
that behaviour is gone and the test should be too.
"""

from django.utils import timezone

from tuckit.core.models import Slice, Ticket
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.slices import allocate_number, create_slice


def legacy_ticket(org, title, *, body="", area=None, status="open",
                  source="human", external_key="", slice_=None):
    """One Ticket row. `status` must satisfy ticket_resolved_at_matches_status,
    so resolved_at is derived from it rather than passed in."""
    return Ticket.objects.create(
        org=org,
        area=area,
        title=title,
        body=body,
        status=status,
        source=source,
        external_key=external_key,
        slice=slice_,
        number=allocate_number(org),
        rank=rank_for(Ticket, {"org": org}),
        resolved_at=timezone.now() if status in Ticket.RESOLVED_STATUSES else None,
    )


def legacy_promoted(org, title, *, area=None, body="", spec=""):
    """A promoted Ticket and the Slice it became, as promote_ticket() left them.

    The Slice reuses the Ticket's number — that is what made the ref survive
    promotion, and it is the join migration 0045 and slice_for_ticket() both
    rely on. Returns (ticket, slice).
    """
    ticket = legacy_ticket(org, title, body=body, area=area)
    slice_ = create_slice(org, area=area, title=title, spec=spec,
                          number=ticket.number)
    ticket.slice = slice_
    ticket.status = "promoted"
    ticket.resolved_at = timezone.now()
    ticket.save(update_fields=["slice", "status", "resolved_at"])
    return ticket, slice_


def legacy_absorbed(ticket, into: Slice):
    """A Ticket folded into an existing Slice: linked and closed, but keeping
    its OWN number — no ref changes hands on an absorb."""
    ticket.slice = into
    ticket.status = "promoted"
    ticket.resolved_at = timezone.now()
    ticket.save(update_fields=["slice", "status", "resolved_at"])
    return ticket


def legacy_resolved(ticket, resolution="dismissed"):
    """A Ticket ended at triage without becoming work."""
    ticket.status = resolution
    ticket.resolved_at = timezone.now()
    ticket.save(update_fields=["status", "resolved_at"])
    return ticket
