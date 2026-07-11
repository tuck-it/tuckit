import pytest

from core.models import Area, Org, Workspace
from core.services.areas import create_area, get_or_create_inbox, list_areas


@pytest.fixture
def workspace(db):
    org = Org.objects.create(name="Acme", slug="acme")
    return Workspace.objects.create(org=org, name="P", slug="p")


@pytest.mark.django_db
def test_create_area_autoslug_and_rank(workspace):
    a = create_area(workspace, "Back End")
    assert a.slug == "back-end"
    assert a.rank


@pytest.mark.django_db
def test_areas_are_ordered_by_creation_rank(workspace):
    a = create_area(workspace, "First")
    b = create_area(workspace, "Second")
    assert list(list_areas(workspace)) == [a, b]
    assert a.rank < b.rank


@pytest.mark.django_db
def test_list_areas_excludes_archived_by_default(workspace):
    a = create_area(workspace, "Kept")
    archived = create_area(workspace, "Gone")
    archived.archived = True
    archived.save()
    assert list(list_areas(workspace)) == [a]
    assert archived in list_areas(workspace, include_archived=True)


@pytest.mark.django_db
def test_duplicate_name_gets_unique_slug(workspace):
    a = create_area(workspace, "Backend")
    b = create_area(workspace, "Backend")
    assert a.slug != b.slug


@pytest.mark.django_db
def test_get_or_create_inbox_is_idempotent_and_single():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    a = get_or_create_inbox(ws)
    b = get_or_create_inbox(ws)
    assert a.id == b.id
    assert a.is_inbox is True
    assert Area.objects.filter(workspace=ws, is_inbox=True).count() == 1


@pytest.mark.django_db
def test_inbox_sorts_before_existing_areas():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    backend = create_area(ws, "Backend")
    inbox = get_or_create_inbox(ws)
    ordered = list(list_areas(ws))
    assert ordered[0].id == inbox.id
    assert ordered[1].id == backend.id
