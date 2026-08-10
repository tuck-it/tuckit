import pytest
from tuckit.core.models import ActivityEvent, Org
from tuckit.core.services.areas import create_area, delete_area
from tuckit.core.services.bites import create_bite, delete_bite
from tuckit.core.services.slices import create_slice


def _org(slug="a"):
    return Org.objects.create(name="Acme", slug=f"acme-{slug}")


@pytest.mark.django_db
def test_create_area_records_created_with_source():
    org = _org("mk")
    area = create_area(org, "Backend", source="agent")
    e = ActivityEvent.objects.get(target_type="area", verb="created")
    assert e.source == "agent" and e.target_label == "Backend" and e.target_id == area.id


@pytest.mark.django_db
def test_create_area_defaults_to_human():
    org = _org("hu")
    create_area(org, "Backend")
    assert ActivityEvent.objects.get(target_type="area", verb="created").source == "human"


@pytest.mark.django_db
def test_delete_area_records_deleted_before_cascade():
    org = _org("del")
    area = create_area(org, "Backend")
    ActivityEvent.objects.all().delete()
    delete_area(area)
    e = ActivityEvent.objects.get(target_type="area", verb="deleted")
    assert e.target_label == "Backend"


@pytest.mark.django_db
def test_delete_bite_records_deleted():
    org = _org("bd")
    s = create_slice(org, area=create_area(org, "A"), title="S", status="open")
    bite = create_bite(s, "Impl")
    ActivityEvent.objects.filter(verb="deleted").delete()
    delete_bite(bite)
    e = ActivityEvent.objects.get(target_type="bite", verb="deleted")
    assert e.target_label == "Impl"
