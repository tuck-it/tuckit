from django.utils import timezone

from tuckit.core.services.refs import slice_ref


def tag_names(slice_) -> list[str]:
    return [t.name for t in slice_.tags.all()]


def slice_dict(slice_, *, now=None) -> dict:
    """One slice, as an agent sees it.

    `age_days` / `idle_days` are whole days, not ISO timestamps: a timestamp
    makes the caller subtract today's date to get the only number it wanted,
    and that is one more place to be wrong.

    Without them the agent-facing board has no time axis at all — a slice
    created five minutes ago and one abandoned forty days ago read identically,
    so nothing ever looks stale to the side that is doing most of the adding.
    The web UI has had this axis all along (services.state.STALE_DAYS, used as
    your_turn()'s sort key); only MCP was blind.

    They are DATA, never a filter. The rule in your_turn() still holds -- "a
    'stale' section is a guilt list: it only grows, and it can never be
    cleared" -- and this changes nothing about what any screen shows.

    Pass `now` when serializing a list, so every row in one response is
    measured from the same instant.
    """
    now = timezone.now() if now is None else now
    return {
        "id": slice_.id,
        "ref": slice_ref(slice_),
        "title": slice_.title,
        "status": slice_.status,
        "tags": tag_names(slice_),
        "area_id": slice_.area_id,
        "assignee": (slice_.assignee.user.email if slice_.assignee_id else None),
        "age_days": (now - slice_.created_at).days,
        "idle_days": (now - slice_.updated_at).days,
    }


def bite_dict(bite) -> dict:
    # No plan_id. The Plan layer is gone from the agent-facing surface, and a
    # key that names it would keep the word alive in the one vocabulary an
    # agent actually reads. The column survives until 0050 drops it.
    return {
        "id": bite.id,
        "title": bite.title,
        "body": bite.body,
        "status": bite.status,
        "slice_id": bite.slice_id,
    }


def area_dict(area) -> dict:
    return {"id": area.id, "name": area.name, "slug": area.slug}


def activity_event_dict(ev) -> dict:
    return {
        "id": ev.id,
        "source": ev.source,
        "member": (ev.member.user.email if ev.member_id else None),
        "verb": ev.verb,
        "body": ev.body,
        "from_value": ev.from_value,
        "to_value": ev.to_value,
        "created_at": ev.created_at.isoformat(),
    }
