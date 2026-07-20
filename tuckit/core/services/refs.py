from tuckit.core.services.exceptions import NotFound


def slice_ref(slice_) -> str:
    """Stable, human-readable ref: '<org-slug>-<number>' (e.g. 'tuck-it-42')."""
    return f"{slice_.area.org.slug}-{slice_.number}"


def parse_slice_ref(org, ref: str) -> int:
    """Return the slice number encoded in `ref`, verifying the slug prefix matches
    `org`. Org slugs may contain '-', so split on the LAST '-'. Raises NotFound."""
    prefix, sep, num = ref.rpartition("-")
    if not sep or prefix != org.slug or not num.isdigit():
        raise NotFound(f"invalid slice ref {ref!r} for org {org.slug!r}")
    return int(num)
