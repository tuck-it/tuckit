import pytest

from tuckit.core.models import Org, Workspace
from tuckit.core.services.tags import get_or_create_tags, list_tags


@pytest.fixture
def ws(db):
    org = Org.objects.create(name="Acme", slug="acme")
    return Workspace.objects.create(org=org, name="P", slug="p")


@pytest.mark.django_db
def test_get_or_create_tags_is_idempotent(ws):
    first = get_or_create_tags(ws.org, ["bug", "someday"])
    second = get_or_create_tags(ws.org, ["bug"])
    assert {t.name for t in first} == {"bug", "someday"}
    assert second[0].id == next(t.id for t in first if t.name == "bug")
    assert list_tags(ws.org).count() == 2
