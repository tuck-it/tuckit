from datetime import timedelta

from django.utils import timezone

from tuckit.core.models import Area, Bite, Slice, Workspace, WorkspaceStatSnapshot
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


def snapshot_today(workspace: Workspace, state: dict) -> dict:
    """Upsert today's count row for `workspace` and return each metric's value
    plus its delta vs the most recent prior-day snapshot. Counts are derived
    from the passed-in home_state so they match the Home buckets exactly
    (e.g. stalled building slices count only toward Needs attention, not
    Building). Lazy — called on Home load, so history accrues without a
    scheduler. delta is None on the first day (no prior row) so the UI shows
    a value with no movement line."""
    today = timezone.localdate()
    building_ct = len(state["building"])
    backlog_ct = len(state["planned"]) + len(state["ideas"]) + len(state["someday"])
    week_ago = timezone.now() - timedelta(days=7)
    shipped_week_ct = sum(
        1 for s in state["shipped"] if s.completed_at and s.completed_at >= week_ago
    )
    attention_ct = len(state["attention"])

    WorkspaceStatSnapshot.objects.update_or_create(
        workspace=workspace,
        date=today,
        defaults={
            "building_ct": building_ct,
            "backlog_ct": backlog_ct,
            "shipped_week_ct": shipped_week_ct,
            "attention_ct": attention_ct,
        },
    )
    prior = (
        WorkspaceStatSnapshot.objects
        .filter(workspace=workspace, date__lt=today)
        .order_by("-date")
        .first()
    )

    def entry(value: int, field: str) -> dict:
        p = getattr(prior, field) if prior else None
        return {"value": value, "delta": None if p is None else value - p}

    return {
        "building": entry(building_ct, "building_ct"),
        "backlog": entry(backlog_ct, "backlog_ct"),
        "shipped_week": entry(shipped_week_ct, "shipped_week_ct"),
        "attention": entry(attention_ct, "attention_ct"),
    }


def attention_items(workspace: Workspace) -> list[dict]:
    now = timezone.now()
    cutoff = now - timedelta(days=STALE_DAYS)
    items: list[dict] = []
    triage = Area.objects.filter(workspace=workspace, is_triage=True).first()
    if triage is not None:
        for s in Slice.objects.filter(area=triage, updated_at__lt=cutoff).exclude(status="dropped").prefetch_related("tags"):
            items.append({"slice": s, "reason": "triage_stale", "days": (now - s.updated_at).days})
    for s in Slice.objects.filter(area__workspace=workspace, status="building", updated_at__lt=cutoff).prefetch_related("tags"):
        items.append({"slice": s, "reason": "building_stalled", "days": (now - s.updated_at).days})
    items.sort(key=lambda it: it["slice"].updated_at)
    return items


def roadmap_state(workspace: Workspace) -> dict:
    """Non-triage, non-dropped slices grouped by roadmap status — powers the
    Roadmap board and its distribution counts."""
    slices = list(
        Slice.objects.filter(area__workspace=workspace, area__is_triage=False)
        .exclude(status="dropped")
        .select_related("area")
        .prefetch_related("tags")
    )

    def bucket(status: str) -> list:
        return sorted(
            [s for s in slices if s.status == status],
            key=lambda s: (s.area.name, s.rank),
        )

    shipped = sorted(
        [s for s in slices if s.status == "shipped"],
        key=lambda s: (s.completed_at or s.updated_at),
        reverse=True,
    )
    return {
        "idea": bucket("idea"),
        "planned": bucket("planned"),
        "building": bucket("building"),
        "shipped": shipped,
    }


ROADMAP_BOARD_ORDER = ["idea", "planned", "building", "shipped"]
ROADMAP_STATUS_KEYS = {"idea", "planned", "building", "shipped"}


def cap_shipped(workspace: Workspace, shipped: list) -> tuple[list, int]:
    """Trim a recency-sorted shipped list to the workspace's board window.
    Returns (visible, total). Pure — operates on an already-fetched list."""
    total = len(shipped)
    if workspace.shipped_board_mode == "days":
        cutoff = timezone.now() - timedelta(days=workspace.shipped_board_limit)
        visible = [s for s in shipped if s.completed_at and s.completed_at >= cutoff]
    else:  # count
        visible = shipped[: workspace.shipped_board_limit]
    return visible, total


def roadmap_board_view(workspace: Workspace) -> dict:
    """Capped kanban groups + shipped overflow meta for the workspace Board tab."""
    state = roadmap_state(workspace)
    visible, total = cap_shipped(workspace, state["shipped"])
    capped = {**state, "shipped": visible}
    return {
        "state": capped,
        "groups": [(status, capped[status]) for status in ROADMAP_BOARD_ORDER],
        "shipped_total": total,
        "shipped_hidden": total - len(visible),
    }


def recent_activity(workspace: Workspace, limit: int = 8) -> list:
    """The workspace's most recent activity events (newest first, capped)."""
    return list(workspace.activity.all()[:limit])


def in_progress_state(workspace: Workspace) -> dict:
    """What's actively being worked right now: building slices + doing bites."""
    slices = list(
        Slice.objects.filter(
            area__workspace=workspace, area__is_triage=False, status="building"
        )
        .select_related("area")
        .prefetch_related("tags")
        .order_by("area__name", "rank")
    )
    bites = list(
        Bite.objects.filter(
            slice__area__workspace=workspace, slice__area__is_triage=False, status="doing"
        )
        .select_related("slice", "slice__area")
        .order_by("slice__area__name", "rank")
    )
    return {"slices": slices, "bites": bites}
