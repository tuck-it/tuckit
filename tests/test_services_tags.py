import pytest

from tuckit.core.models import Org, Workspace
from tuckit.core.services.tags import get_or_create_tags, list_tags


@pytest.fixture
def workspace(db):
    org = Org.objects.create(name="Acme", slug="acme")
    return Workspace.objects.create(org=org, name="P", slug="p")


@pytest.mark.django_db
def test_get_or_create_tags_is_idempotent(workspace):
    first = get_or_create_tags(workspace, ["bug", "someday"])
    second = get_or_create_tags(workspace, ["bug"])
    assert {t.name for t in first} == {"bug", "someday"}
    assert second[0].id == next(t.id for t in first if t.name == "bug")
    assert list_tags(workspace).count() == 2
