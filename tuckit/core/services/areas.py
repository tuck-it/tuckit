from django.db.models import QuerySet
from django.utils.text import slugify

from tuckit.core.models import Area, Org
from tuckit.core.services.activity import record_activity
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.exceptions import InvalidValue


def list_areas(org: Org, include_archived: bool = False) -> QuerySet:
    qs = Area.objects.filter(org=org)
    if not include_archived:
        qs = qs.filter(archived=False)
    return qs


def _unique_slug(org: Org, name: str) -> str:
    base = slugify(name) or "area"
    slug = base
    i = 2
    while Area.objects.filter(org=org, slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def create_area(org: Org, name: str, description: str = "", slug: str | None = None,
                *, source: str = "human", member=None) -> Area:
    slug = slug or _unique_slug(org, name)
    rank = rank_for(Area, {"org": org})
    area = Area.objects.create(
        org=org, name=name, description=description, slug=slug, rank=rank
    )
    record_activity(org, source=source, verb="created", target=area, member=member)
    return area


def update_area(area: Area, *, name: str | None = None, description: str | None = None) -> Area:
    fields = ["updated_at"]
    if name is not None:
        name = name.strip()
        if not name:
            raise InvalidValue("Please enter a name")
        area.name = name
        fields.append("name")
    if description is not None:
        area.description = description.strip()
        fields.append("description")
    area.save(update_fields=fields)
    return area


def delete_area(area: Area, *, member=None) -> None:
    # Record before the row goes; target_label is denormalized so the log
    # renders after the area is gone.
    record_activity(area.org, source="human", verb="deleted", target=area, member=member)
    # NOT a cascade. Slice.area is on_delete=SET_NULL since 0044, so the
    # area's slices survive with area=NULL — i.e. they go back to the Inbox,
    # where they can be filed into another area. The delete confirmation in
    # _area_row.html says exactly that; keep the two in step.
    area.delete()


def reorder_area(area: Area, *, before: Area | None = None, after: Area | None = None) -> Area:
    area.rank = rank_for(Area, {"org": area.org}, before=before, after=after)
    area.save(update_fields=["rank", "updated_at"])
    return area
