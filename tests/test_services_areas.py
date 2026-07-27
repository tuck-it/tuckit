import pytest

from tuckit.core.models import Area, Org
from tuckit.core.services.areas import create_area, list_areas, update_area, delete_area, reorder_area
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slices import create_slice


@pytest.fixture
def org(db):
    return Org.objects.create(name="Acme", slug="acme")


@pytest.mark.django_db
def test_create_area_autoslug_and_rank(org):
    a = create_area(org, "Back End")
    assert a.slug == "back-end"
    assert a.rank


@pytest.mark.django_db
def test_areas_are_ordered_by_creation_rank(org):
    a = create_area(org, "First")
    b = create_area(org, "Second")
    assert list(list_areas(org)) == [a, b]
    assert a.rank < b.rank


@pytest.mark.django_db
def test_list_areas_excludes_archived_by_default(org):
    a = create_area(org, "Kept")
    archived = create_area(org, "Gone")
    archived.archived = True
    archived.save()
    assert list(list_areas(org)) == [a]
    assert archived in list_areas(org, include_archived=True)


@pytest.mark.django_db
def test_duplicate_name_gets_unique_slug(org):
    a = create_area(org, "Backend")
    b = create_area(org, "Backend")
    assert a.slug != b.slug


@pytest.mark.django_db
def test_update_area_changes_name_but_keeps_slug(org):
    a = create_area(org, "Back End")
    original_slug = a.slug
    updated = update_area(a, name="Platform")
    a.refresh_from_db()
    assert a.name == "Platform"
    assert a.slug == original_slug
    assert updated.id == a.id


@pytest.mark.django_db
def test_update_area_sets_description(org):
    a = create_area(org, "Backend")
    update_area(a, description="APIs and background jobs")
    a.refresh_from_db()
    assert a.description == "APIs and background jobs"


@pytest.mark.django_db
def test_update_area_name_and_description_together(org):
    a = create_area(org, "Old", description="old")
    update_area(a, name="New", description="new")
    a.refresh_from_db()
    assert a.name == "New"
    assert a.description == "new"


@pytest.mark.django_db
def test_update_area_trims_whitespace(org):
    a = create_area(org, "X")
    update_area(a, name="  Trimmed  ", description="  d  ")
    a.refresh_from_db()
    assert a.name == "Trimmed"
    assert a.description == "d"


@pytest.mark.django_db
def test_update_area_rejects_blank_name(org):
    a = create_area(org, "Keep")
    with pytest.raises(InvalidValue):
        update_area(a, name="   ")
    a.refresh_from_db()
    assert a.name == "Keep"


@pytest.mark.django_db
def test_update_area_description_only_keeps_name(org):
    a = create_area(org, "Keep")
    update_area(a, description="just a desc")
    a.refresh_from_db()
    assert a.name == "Keep"
    assert a.description == "just a desc"


@pytest.mark.django_db
def test_delete_area_removes_it_and_sends_slices_to_inbox(org):
    a = create_area(org, "Doomed")
    child = create_slice(a, "child planned", status="open", source="human")
    delete_area(a)
    assert not Area.objects.filter(org=org, name="Doomed").exists()
    child.refresh_from_db()
    assert child.area_id is None


@pytest.mark.django_db
def test_reorder_area_moves_before_sibling(org):
    a = create_area(org, "A")
    b = create_area(org, "B")
    c = create_area(org, "C")
    # move c before a  ->  C, A, B
    reorder_area(c, before=a)
    ordered = list(list_areas(org))
    assert [x.id for x in ordered] == [c.id, a.id, b.id]


@pytest.mark.django_db
def test_reorder_area_moves_after_sibling(org):
    a = create_area(org, "A")
    b = create_area(org, "B")
    c = create_area(org, "C")
    # move a after b  ->  B, A, C
    reorder_area(a, after=b)
    ordered = list(list_areas(org))
    assert [x.id for x in ordered] == [b.id, a.id, c.id]
