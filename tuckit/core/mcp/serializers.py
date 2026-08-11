from tuckit.core.services.refs import slice_ref


def tag_names(slice_) -> list[str]:
    return [t.name for t in slice_.tags.all()]


def slice_dict(slice_) -> dict:
    return {
        "id": slice_.id,
        "ref": slice_ref(slice_),
        "title": slice_.title,
        "status": slice_.status,
        "tags": tag_names(slice_),
        "area_id": slice_.area_id,
        "assignee": (slice_.assignee.user.email if slice_.assignee_id else None),
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
