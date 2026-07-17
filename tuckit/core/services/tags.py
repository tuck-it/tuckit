from django.db.models import QuerySet

from tuckit.core.models import Org, Tag


def get_or_create_tags(org: Org, names: list[str]) -> list[Tag]:
    tags = []
    for name in names:
        tag, _ = Tag.objects.get_or_create(org=org, name=name)
        tags.append(tag)
    return tags


def list_tags(org: Org) -> QuerySet:
    return Tag.objects.filter(org=org).order_by("name")
