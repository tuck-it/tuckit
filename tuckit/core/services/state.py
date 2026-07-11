from datetime import timedelta

from django.utils import timezone

from tuckit.core.models import Area, Slice, Workspace
from tuckit.core.services.areas import list_areas
from tuckit.core.services.bites import list_bites
from tuckit.core.services.slices import list_slices

_OPEN_BITE_STATUSES = ["todo", "doing"]
STALE_DAYS = 7


def _tag_names(slice_: Slice) -> list[str]:
    return [t.name for t in slice_.tags.all()]


def _slice_brief(slice_: Slice) -> dict:
    return {"id": slice_.id, "title": slice_.title, "tags": _tag_names(slice_)}


def _area_state(area: Area) -> dict:
    slices = list(list_slices(area).prefetch_related("tags"))
    shipped = [s for s in slices if s.status == "shipped"]
    someday = [s for s in slices if "someday" in _tag_names(s) and s.status != "shipped"]
    someday_ids = {s.id for s in someday}
    building = [s for s in slices if s.status == "building" and s.id not in someday_ids]
    planned = [s for s in slices if s.status == "planned" and s.id not in someday_ids]
    ideas = [s for s in slices if s.status == "idea" and s.id not in someday_ids]

    building_out = []
    open_bite_count = 0
    for s in building:
        open_bites = [b for b in list_bites(s) if b.status in _OPEN_BITE_STATUSES]
        open_bite_count += len(open_bites)
        building_out.append(
            {
                "id": s.id,
                "title": s.title,
                "open_bites": [
                    {"id": b.id, "title": b.title, "status": b.status} for b in open_bites
                ],
            }
        )

    return {
        "name": area.name,
        "slug": area.slug,
        "shipped": [_slice_brief(s) for s in shipped],
        "building": building_out,
        "roadmap": [_slice_brief(s) for s in planned],
        "ideas": [{"id": s.id, "title": s.title} for s in ideas],
        "someday": [{"id": s.id, "title": s.title} for s in someday],
        "counts": {"open_bites": open_bite_count, "shipped": len(shipped)},
    }


def get_project_state(workspace: Workspace, area: Area | None = None) -> dict:
    areas = [area] if area is not None else list(list_areas(workspace))
    return {
        "product": {"name": workspace.name, "description": workspace.description},
        "areas": [_area_state(a) for a in areas],
    }


def render_slice_markdown(slice_: Slice) -> str:
    tags = " ".join(f"#{t}" for t in _tag_names(slice_))
    lines = [f"# {slice_.title}", "", f"Status: {slice_.status}"]
    if tags:
        lines[-1] += f" · {tags}"
    lines.append("")
    if slice_.spec:
        lines += [slice_.spec, ""]
    bites = list(list_bites(slice_))
    if bites:
        lines.append("## Bites")
        for b in bites:
            check = "x" if b.status == "done" else " "
            lines.append(f"- [{check}] {b.title}")
    return "\n".join(lines).rstrip() + "\n"


def home_state(workspace: Workspace) -> dict:
    slices = list(
        Slice.objects.filter(area__workspace=workspace)
        .select_related("area").prefetch_related("tags")
    )
    someday = [s for s in slices if "someday" in _tag_names(s) and s.status != "shipped"]
    someday_ids = {s.id for s in someday}
    attention = attention_items(workspace)
    attention_ids = {it["slice"].id for it in attention}
    hidden_ids = someday_ids | attention_ids

    def bucket(status):
        return sorted(
            [s for s in slices if s.status == status and s.id not in hidden_ids],
            key=lambda s: (s.area.name, s.rank),
        )

    shipped = sorted(
        [s for s in slices if s.status == "shipped"],
        key=lambda s: s.completed_at or s.updated_at, reverse=True,
    )
    return {
        "attention": attention,
        "building": bucket("building"),
        "planned": bucket("planned"),
        "ideas": bucket("idea"),
        "someday": someday,
        "shipped": shipped,
    }


def attention_items(workspace: Workspace) -> list[dict]:
    now = timezone.now()
    cutoff = now - timedelta(days=STALE_DAYS)
    items: list[dict] = []
    inbox = Area.objects.filter(workspace=workspace, is_inbox=True).first()
    if inbox is not None:
        for s in Slice.objects.filter(area=inbox, updated_at__lt=cutoff).exclude(status="dropped"):
            items.append({"slice": s, "reason": "inbox_stale", "days": (now - s.updated_at).days})
    for s in Slice.objects.filter(area__workspace=workspace, status="building", updated_at__lt=cutoff):
        items.append({"slice": s, "reason": "building_stalled", "days": (now - s.updated_at).days})
    items.sort(key=lambda it: it["slice"].updated_at)
    return items
