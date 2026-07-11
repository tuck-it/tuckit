def tag_names(slice_) -> list[str]:
    return [t.name for t in slice_.tags.all()]


def slice_dict(slice_) -> dict:
    return {
        "id": slice_.id,
        "title": slice_.title,
        "status": slice_.status,
        "tags": tag_names(slice_),
        "area_id": slice_.area_id,
    }


def bite_dict(bite) -> dict:
    return {
        "id": bite.id,
        "title": bite.title,
        "status": bite.status,
        "slice_id": bite.slice_id,
    }


def area_dict(area) -> dict:
    return {"id": area.id, "name": area.name, "slug": area.slug}
