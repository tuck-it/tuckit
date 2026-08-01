from tuckit.core.services.exceptions import NotFound


def slice_ref(slice_) -> str:
    """Stable, human-readable ref: '<ORG-KEY>-<number>' (e.g. 'TUC-42').

    Reads the denormalized slice_.org column rather than crossing through the
    slice's area: that column exists for exactly this, and a ref now renders
    on every row of every list."""
    return f"{slice_.org.key}-{slice_.number}"


def ref_for(obj) -> str:
    """Dispatch to the right formatter. Used by the {% ref_of %} template tag so
    templates never assemble a ref themselves.

    One case, since 0050 dropped the Ticket table: a Slice is the only thing
    that carries a number. The dispatch stays rather than collapsing into
    slice_ref() because the template tag is the caller, and a tag that raises
    TypeError on the wrong object beats one that renders 'None-None'."""
    from tuckit.core.models import Slice

    if isinstance(obj, Slice):
        return slice_ref(obj)
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
