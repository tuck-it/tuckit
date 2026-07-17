from django.db.models import QuerySet
from django.utils.text import slugify

from tuckit.core.models import Area, Workspace
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.exceptions import InvalidValue

TRIAGE_NAME = "Triage"


def list_areas(workspace: Workspace, include_archived: bool = False) -> QuerySet:
    qs = Area.objects.filter(workspace=workspace)
    if not include_archived:
        qs = qs.filter(archived=False)
    return qs


def _unique_slug(workspace: Workspace, name: str) -> str:
    base = slugify(name) or "area"
    slug = base
    i = 2
    while Area.objects.filter(workspace=workspace, slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def create_area(workspace: Workspace, name: str, description: str = "", slug: str | None = None) -> Area:
    slug = slug or _unique_slug(workspace, name)
    rank = rank_for(Area, {"workspace": workspace})
    return Area.objects.create(
        workspace=workspace, org=workspace.org, name=name, description=description, slug=slug, rank=rank
    )


def get_or_create_triage(workspace: Workspace) -> Area:
    triage = Area.objects.filter(workspace=workspace, is_triage=True).first()
    if triage is not None:
        return triage
    first = Area.objects.filter(workspace=workspace).order_by("rank").first()
    rank = rank_for(Area, {"workspace": workspace}, before=first)
    return Area.objects.create(
        workspace=workspace,
        org=workspace.org,
        name=TRIAGE_NAME,
        slug=_unique_slug(workspace, TRIAGE_NAME),
        is_triage=True,
        rank=rank,
    )


def rename_area(area: Area, name: str) -> Area:
    name = (name or "").strip()
    if not name:
        raise InvalidValue("이름을 입력해주세요")
    area.name = name
    area.save(update_fields=["name", "updated_at"])
    return area


def delete_area(area: Area) -> None:
    if area.is_triage:
        raise InvalidValue("Triage는 삭제할 수 없습니다")
    area.delete()  # cascades to slices/bites via FK on_delete=CASCADE


def reorder_area(area: Area, *, before: Area | None = None, after: Area | None = None) -> Area:
    area.rank = rank_for(Area, {"workspace": area.workspace}, before=before, after=after)
    area.save(update_fields=["rank", "updated_at"])
    return area
