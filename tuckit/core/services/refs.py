from tuckit.core.services.exceptions import NotFound


def slice_ref(slice_) -> str:
    """Stable, human-readable ref: '<ORG-KEY>-<number>' (e.g. 'TUC-42').

    Reads slice_.org, not slice_.area.org: the denormalized column exists for
    exactly this, and a ref now renders on every row of every list."""
    return f"{slice_.org.key}-{slice_.number}"


def ticket_ref(ticket) -> str:
    """Stable ref for a Ticket. Shares the Slice number space, so a promoted
    Ticket's Slice keeps the same ref."""
    return f"{ticket.org.key}-{ticket.number}"


def ref_for(obj) -> str:
    """Dispatch to the right formatter. Used by the {% ref_of %} template tag so
    templates never assemble a ref themselves."""
    from tuckit.core.models import Slice, Ticket

    if isinstance(obj, Slice):
        return slice_ref(obj)
    if isinstance(obj, Ticket):
        return ticket_ref(obj)
    raise TypeError(f"no ref for {type(obj).__name__}")


def parse_ref(org, ref: str) -> int:
    """Return the number encoded in `ref`, verifying the key prefix matches
    `org`. Accepts 'TUC-47' and 'tuc-47'.

    Does NOT accept a bare '47' — get_slice_flexible() reads bare digits as
    primary keys, and quietly changing that would reroute existing MCP calls.
    The search view handles bare numbers itself.

    Does NOT accept the pre-key '<org-slug>-<n>' form. Raises NotFound."""
    prefix, sep, num = (ref or "").strip().rpartition("-")
    if not sep or prefix.upper() != org.key or not num.isdigit():
        raise NotFound(f"invalid ref {ref!r} for org {org.key!r}")
    return int(num)
