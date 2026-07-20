from tuckit.core.services.refs import slice_ref, ticket_ref


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


def ticket_dict(ticket) -> dict:
    return {
        "id": ticket.id,
        "ref": ticket_ref(ticket),
        "title": ticket.title,
        "status": ticket.status,
        "area_id": ticket.area_id,
        "created_by": (ticket.created_by.user.email if ticket.created_by_id else None),
        "source": ticket.source,
    }


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
