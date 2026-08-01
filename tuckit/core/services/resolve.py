from tuckit.core.models import Area, Bite, Org, Slice
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


# No resolve_ref(), get_ticket(), get_ticket_by_ref() or slice_for_ticket().
# All four existed to answer "what does this pre-two-layer identifier mean
# now?", and every one of them read the Ticket table to do it. 0050 drops that
# table, so there is nothing left to read: a ref is a Slice number and nothing
# else, which is exactly get_slice_by_ref() above. resolve_ref() in particular
# had already collapsed to the same query — keeping the second spelling would
# have left two names for one lookup, drifting apart on the next change.
