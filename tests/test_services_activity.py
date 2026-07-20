import pytest
from tuckit.core.models import ActivityEvent, Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.activity import record_activity, status_verb


def _org(slug="w"):
    return Org.objects.create(name="Acme", slug=f"acme-{slug}")


@pytest.mark.django_db
def test_record_activity_derives_target_fields():
    org = _org()
    a = create_area(org, "Backend")
    s = create_slice(a, "Payment integration", status="idea")
    ActivityEvent.objects.all().delete()  # ignore the create_slice event from Task 2
    record_activity(org, actor="agent", verb="status_changed", target=s, from_value="idea", to_value="building")
    e = ActivityEvent.objects.get()
    assert e.org_id == org.id
    assert e.actor == "agent" and e.verb == "status_changed"
    assert e.target_type == "slice" and e.target_id == s.id
    assert e.target_label == "Payment integration"
    assert e.from_value == "idea" and e.to_value == "building"


@pytest.mark.django_db
def test_record_activity_survives_target_deletion():
    org = _org("w2")
    a = create_area(org, "Backend")
    s = create_slice(a, "To be deleted")
    ActivityEvent.objects.all().delete()
    record_activity(org, actor="human", verb="created", target=s)
    s.delete()
    e = ActivityEvent.objects.get()   # log row still there
    assert e.target_label == "To be deleted" and e.target_id is not None


def test_status_verb_maps_terminal_states():
    assert status_verb("shipped") == "shipped"
    assert status_verb("dropped") == "dropped"
    assert status_verb("building") == "status_changed"
    assert status_verb("done") == "status_changed"


@pytest.mark.django_db
def test_add_note_appends_noted_event_with_body():
    from tuckit.core.services.activity import add_note, slice_activity

    org = _org("note")
    s = create_slice(create_area(org, "B"), "Auth")
    ev = add_note(s, "Shipped behind flag; see PR #12.", actor="agent")
    assert ev.verb == "noted" and ev.actor == "agent"
    assert ev.body == "Shipped behind flag; see PR #12."
    assert [e.id for e in slice_activity(s)][-1] == ev.id
