from tuckit.core.models import Area, Bite, Slice, Workspace
from tuckit.core.services.exceptions import NotFound


def get_area(workspace: Workspace, area_id: int) -> Area:
    try:
        return Area.objects.get(pk=area_id, workspace=workspace)
    except Area.DoesNotExist:
        raise NotFound(f"area {area_id} not found")


def get_area_by_slug(workspace: Workspace, slug: str) -> Area:
    try:
        return Area.objects.get(slug=slug, workspace=workspace)
    except Area.DoesNotExist:
        raise NotFound(f"area {slug} not found")


def get_slice(workspace: Workspace, slice_id: int) -> Slice:
    try:
        return Slice.objects.get(pk=slice_id, area__workspace=workspace)
    except Slice.DoesNotExist:
        raise NotFound(f"slice {slice_id} not found")


def get_bite(workspace: Workspace, bite_id: int) -> Bite:
    try:
        return Bite.objects.get(pk=bite_id, slice__area__workspace=workspace)
    except Bite.DoesNotExist:
        raise NotFound(f"bite {bite_id} not found")
