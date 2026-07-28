from tuckit.core.models import Area, Bite, Org, Slice, Ticket
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.refs import parse_ref


def get_area(org: Org, area_id: int) -> Area:
    try:
        return Area.objects.get(pk=area_id, org=org)
    except Area.DoesNotExist:
        raise NotFound(f"area {area_id} not found")


def get_area_by_slug(org: Org, slug: str) -> Area:
    try:
        return Area.objects.get(slug=slug, org=org)
    except Area.DoesNotExist:
        raise NotFound(f"area {slug} not found")


def get_slice(org: Org, slice_id: int) -> Slice:
    try:
        return Slice.objects.get(pk=slice_id, org=org)
    except Slice.DoesNotExist:
        raise NotFound(f"slice {slice_id} not found")


def get_bite(org: Org, bite_id: int) -> Bite:
    try:
        return Bite.objects.get(pk=bite_id, slice__org=org)
    except Bite.DoesNotExist:
        raise NotFound(f"bite {bite_id} not found")


def get_slice_by_ref(org: Org, ref: str) -> Slice:
    number = parse_ref(org, ref)
    try:
        return Slice.objects.get(number=number, org=org)
    except Slice.DoesNotExist:
        raise NotFound(f"slice {ref} not found")


def get_slice_flexible(org: Org, id_or_ref) -> Slice:
    """Accept an int id or a string ref ('<ORG-KEY>-<n>')."""
    if isinstance(id_or_ref, int) or (isinstance(id_or_ref, str) and id_or_ref.isdigit()):
        return get_slice(org, int(id_or_ref))
    return get_slice_by_ref(org, id_or_ref)


def get_ticket(org: Org, ticket_id: int) -> Ticket:
    try:
        return Ticket.objects.get(pk=ticket_id, org=org)
    except Ticket.DoesNotExist:
        raise NotFound(f"ticket {ticket_id} not found")


def get_ticket_by_ref(org: Org, ref: str) -> Ticket:
    number = parse_ref(org, ref)
    try:
        return Ticket.objects.get(number=number, org=org)
    except Ticket.DoesNotExist:
        raise NotFound(f"ticket {ref} not found")


def slice_for_ticket(org: Org, ticket_id: int) -> Slice | None:
    """The Slice a Ticket became, or None.

    Legacy read path, for links that were handed out before Tickets stopped
    being a surface (`?ticket=<id>` bookmarks, refs in commit messages and
    memory). Two threads lead back:

    - a ticket that was promoted or absorbed carries `ticket.slice`;
    - a ticket that was never triaged became a NEW slice in migration 0045,
      which inherited its `number` (uniq_slice_number_per_org makes that
      lookup unambiguous).

    Lives here, next to resolve_ref(), because it is the same job — take an
    identifier from before the two-layer model and hand back what it means now.
    Its old home, the tickets service module, is gone: nothing writes a
    Ticket any more, so only the reading half survives. Both threads are readable only
    while the Ticket table survives — 0047 drops it, and this goes with it.
    """
    ticket = Ticket.objects.filter(org=org, pk=ticket_id).first()
    if ticket is None:
        return None
    # `ticket.slice` is a plain FK now, but the getattr default is kept: it
    # costs nothing and covers the null case in one expression.
    return getattr(ticket, "slice", None) or Slice.objects.filter(
        org=org, number=ticket.number
    ).first()


def resolve_ref(org: Org, ref: str):
    """Resolve a '<ORG-KEY>-<n>' ref to its current form: the Slice with that
    number if one exists (i.e. the Ticket was promoted), the Slice that
    absorbed the Ticket if it was folded into other work, otherwise the
    Ticket itself."""
    number = parse_ref(org, ref)
    s = Slice.objects.filter(number=number, org=org).first()
    if s is not None:
        return s
    t = Ticket.objects.filter(number=number, org=org).first()
    if t is not None:
        # An absorbed ticket's work lives under another ref. Follow the explicit
        # link rather than the number, which only ever finds origins.
        return t.slice or t
    raise NotFound(f"ref {ref} not found for org {org.slug!r}")
