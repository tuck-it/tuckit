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
    }


def bite_dict(bite) -> dict:
    return {
        "id": bite.id,
        "title": bite.title,
        "body": bite.body,
        "status": bite.status,
        "plan_id": bite.plan_id,
        "slice_id": bite.plan.slice_id,
    }


def plan_dict(plan) -> dict:
    return {
        "id": plan.id,
        "slice_id": plan.slice_id,
        "title": plan.title,
        "body": plan.body,
        "constraints": plan.constraints,
    }


def area_dict(area) -> dict:
    return {"id": area.id, "name": area.name, "slug": area.slug}


def activity_event_dict(ev) -> dict:
    return {
        "id": ev.id,
        "actor": ev.actor,
        "verb": ev.verb,
        "body": ev.body,
        "from_value": ev.from_value,
        "to_value": ev.to_value,
        "created_at": ev.created_at.isoformat(),
    }
