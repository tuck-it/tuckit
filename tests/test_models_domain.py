import pytest
from django.db import IntegrityError

from tuckit.core.models import Area, Bite, Org, Slice, Tag, Workspace


@pytest.fixture
def workspace(db):
    org = Org.objects.create(name="Acme", slug="acme")
    return Workspace.objects.create(org=org, name="P", slug="p")


@pytest.mark.django_db
def test_area_slug_unique_per_workspace(workspace):
    Area.objects.create(workspace=workspace, name="Backend", slug="backend", rank="a0")
    with pytest.raises(IntegrityError):
        Area.objects.create(workspace=workspace, name="Backend2", slug="backend", rank="a1")


@pytest.mark.django_db
def test_slice_defaults(workspace):
    area = Area.objects.create(workspace=workspace, name="Backend", slug="backend", rank="a0")
    s = Slice.objects.create(area=area, title="Auth", rank="a0")
    assert s.status == "idea"
    assert s.spec == ""
    assert s.source == "human"
    assert s.completed_at is None


@pytest.mark.django_db
def test_slice_tags_are_workspace_tags(workspace):
    area = Area.objects.create(workspace=workspace, name="Backend", slug="backend", rank="a0")
    s = Slice.objects.create(area=area, title="Auth", rank="a0")
    tag = Tag.objects.create(workspace=workspace, name="bug")
    s.tags.add(tag)
    assert list(s.tags.all()) == [tag]


@pytest.mark.django_db
def test_tag_unique_per_workspace(workspace):
    Tag.objects.create(workspace=workspace, name="bug")
    with pytest.raises(IntegrityError):
        Tag.objects.create(workspace=workspace, name="bug")


@pytest.mark.django_db
def test_bite_requires_slice(workspace):
    area = Area.objects.create(workspace=workspace, name="Backend", slug="backend", rank="a0")
    s = Slice.objects.create(area=area, title="Auth", rank="a0")
    b = Bite.objects.create(slice=s, title="JWT", rank="a0")
    assert b.status == "todo"
    assert b.slice_id == s.id
