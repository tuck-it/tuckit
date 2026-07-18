from django.db.models import QuerySet
from django.utils.text import slugify

from tuckit.core.models import Area, Org
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.exceptions import InvalidValue

TRIAGE_NAME = "Triage"


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


def create_area(org: Org, name: str, description: str = "", slug: str | None = None) -> Area:
    slug = slug or _unique_slug(org, name)
    rank = rank_for(Area, {"org": org})
    return Area.objects.create(
        org=org, name=name, description=description, slug=slug, rank=rank
    )


def get_or_create_triage(org: Org) -> Area:
    triage = Area.objects.filter(org=org, is_triage=True).first()
    if triage is not None:
        return triage
    first = Area.objects.filter(org=org).order_by("rank").first()
    rank = rank_for(Area, {"org": org}, before=first)
    return Area.objects.create(
        org=org,
        name=TRIAGE_NAME,
        slug=_unique_slug(org, TRIAGE_NAME),
        is_triage=True,
        rank=rank,
    )


def update_area(area: Area, *, name: str | None = None, description: str | None = None) -> Area:
    fields = ["updated_at"]
    if name is not None:
        name = name.strip()
        if not name:
            raise InvalidValue("이름을 입력해주세요")
        area.name = name
        fields.append("name")
    if description is not None:
        area.description = description.strip()
        fields.append("description")
    area.save(update_fields=fields)
    return area


def delete_area(area: Area) -> None:
    if area.is_triage:
        raise InvalidValue("Triage는 삭제할 수 없습니다")
    area.delete()  # cascades to slices/bites via FK on_delete=CASCADE


def reorder_area(area: Area, *, before: Area | None = None, after: Area | None = None) -> Area:
    area.rank = rank_for(Area, {"org": area.org}, before=before, after=after)
    area.save(update_fields=["rank", "updated_at"])
    return area
