import pytest
from tuckit.core.models import ActivityEvent, Org, Workspace
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.slices import create_slice, set_slice_status, set_slice_area, update_slice


def _ws(slug="w"):
    org = Org.objects.create(name="Acme", slug=f"acme-{slug}")
    return Workspace.objects.create(org=org, name="W", slug=slug)


@pytest.mark.django_db
def test_create_slice_records_created_with_source_actor():
    ws = _ws()
    a = create_area(ws.org, "Backend")
    create_slice(a, "결제", status="idea", source="agent")
    e = ActivityEvent.objects.get(verb="created")
    assert e.actor == "agent" and e.target_type == "slice" and e.target_label == "결제"


@pytest.mark.django_db
def test_set_slice_status_records_transition():
    ws = _ws("w2")
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "결제", status="planned")
    ActivityEvent.objects.all().delete()
    set_slice_status(s, "building", actor="agent")
    e = ActivityEvent.objects.get()
    assert e.verb == "status_changed" and e.actor == "agent"
    assert e.from_value == "planned" and e.to_value == "building"


@pytest.mark.django_db
def test_set_slice_status_shipped_uses_shipped_verb():
    ws = _ws("w3")
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "결제", status="building")
    ActivityEvent.objects.all().delete()
    set_slice_status(s, "shipped")
    assert ActivityEvent.objects.get().verb == "shipped"


@pytest.mark.django_db
def test_set_slice_status_noop_records_nothing():
    ws = _ws("w4")
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "결제", status="building")
    ActivityEvent.objects.all().delete()
    set_slice_status(s, "building")   # same status
    assert ActivityEvent.objects.count() == 0


@pytest.mark.django_db
def test_set_slice_area_records_triaged_when_leaving_triage():
    ws = _ws("w5")
    triage = get_or_create_triage(ws.org)
    backend = create_area(ws.org, "Backend")
    s = create_slice(triage, "옮길 것")
    ActivityEvent.objects.all().delete()
    set_slice_area(s, backend)
    e = ActivityEvent.objects.get()
    assert e.verb == "triaged" and e.to_value == "Backend"


@pytest.mark.django_db
def test_set_slice_area_records_moved_between_real_areas():
    ws = _ws("w6")
    a1 = create_area(ws.org, "A1")
    a2 = create_area(ws.org, "A2")
    s = create_slice(a1, "이동")
    ActivityEvent.objects.all().delete()
    set_slice_area(s, a2)
    assert ActivityEvent.objects.get().verb == "moved"


@pytest.mark.django_db
def test_update_slice_records_only_on_status_change():
    ws = _ws("w7")
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "제목", status="idea")
    ActivityEvent.objects.all().delete()
    update_slice(s, title="새 제목")            # edit only -> no event
    assert ActivityEvent.objects.count() == 0
    update_slice(s, status="planned")           # status -> one event
    assert ActivityEvent.objects.get().verb == "status_changed"


@pytest.mark.django_db
def test_set_slice_area_same_area_records_nothing():
    # Concurrent re-triage / stale-row resubmit: assigning the slice's current
    # area must not log a spurious moved/triaged event (from == to).
    ws = _ws("w8")
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "그대로")
    ActivityEvent.objects.all().delete()
    set_slice_area(s, a)
    assert ActivityEvent.objects.count() == 0
