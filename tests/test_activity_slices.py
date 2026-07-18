import pytest
from tuckit.core.models import ActivityEvent, Org
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.slices import create_slice, set_slice_status, set_slice_area, update_slice


def _org(slug="w"):
    return Org.objects.create(name="Acme", slug=f"acme-{slug}")


@pytest.mark.django_db
def test_create_slice_records_created_with_source_actor():
    org = _org()
    a = create_area(org, "Backend")
    create_slice(a, "Payment", status="idea", source="agent")
    e = ActivityEvent.objects.get(verb="created")
    assert e.actor == "agent" and e.target_type == "slice" and e.target_label == "Payment"


@pytest.mark.django_db
def test_set_slice_status_records_transition():
    org = _org("w2")
    a = create_area(org, "Backend")
    s = create_slice(a, "Payment", status="planned")
    ActivityEvent.objects.all().delete()
    set_slice_status(s, "building", actor="agent")
    e = ActivityEvent.objects.get()
    assert e.verb == "status_changed" and e.actor == "agent"
    assert e.from_value == "planned" and e.to_value == "building"


@pytest.mark.django_db
def test_set_slice_status_shipped_uses_shipped_verb():
    org = _org("w3")
    a = create_area(org, "Backend")
    s = create_slice(a, "Payment", status="building")
    ActivityEvent.objects.all().delete()
    set_slice_status(s, "shipped")
    assert ActivityEvent.objects.get().verb == "shipped"


@pytest.mark.django_db
def test_set_slice_status_noop_records_nothing():
    org = _org("w4")
    a = create_area(org, "Backend")
    s = create_slice(a, "Payment", status="building")
    ActivityEvent.objects.all().delete()
    set_slice_status(s, "building")   # same status
    assert ActivityEvent.objects.count() == 0


@pytest.mark.django_db
def test_set_slice_area_records_triaged_when_leaving_triage():
    org = _org("w5")
    triage = get_or_create_triage(org)
    backend = create_area(org, "Backend")
    s = create_slice(triage, "To move")
    ActivityEvent.objects.all().delete()
    set_slice_area(s, backend)
    e = ActivityEvent.objects.get()
    assert e.verb == "triaged" and e.to_value == "Backend"


@pytest.mark.django_db
def test_set_slice_area_records_moved_between_real_areas():
    org = _org("w6")
    a1 = create_area(org, "A1")
    a2 = create_area(org, "A2")
    s = create_slice(a1, "Move")
    ActivityEvent.objects.all().delete()
    set_slice_area(s, a2)
    assert ActivityEvent.objects.get().verb == "moved"


@pytest.mark.django_db
def test_update_slice_records_only_on_status_change():
    org = _org("w7")
    a = create_area(org, "Backend")
    s = create_slice(a, "Title", status="idea")
    ActivityEvent.objects.all().delete()
    update_slice(s, title="New title")           # edit only -> no event
    assert ActivityEvent.objects.count() == 0
    update_slice(s, status="planned")           # status -> one event
    assert ActivityEvent.objects.get().verb == "status_changed"


@pytest.mark.django_db
def test_set_slice_area_same_area_records_nothing():
    # Concurrent re-triage / stale-row resubmit: assigning the slice's current
    # area must not log a spurious moved/triaged event (from == to).
    org = _org("w8")
    a = create_area(org, "Backend")
    s = create_slice(a, "Unchanged")
    ActivityEvent.objects.all().delete()
    set_slice_area(s, a)
    assert ActivityEvent.objects.count() == 0
