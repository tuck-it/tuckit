from django.db.models import QuerySet

from tuckit.core.models import Tag, Workspace


def get_or_create_tags(workspace: Workspace, names: list[str]) -> list[Tag]:
    tags = []
    for name in names:
        tag, _ = Tag.objects.get_or_create(workspace=workspace, name=name)
        tags.append(tag)
    return tags


def list_tags(workspace: Workspace) -> QuerySet:
    return Tag.objects.filter(workspace=workspace).order_by("name")
