import pytest
from tuckit.core.models import ActivityEvent, Org, Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.activity import record_activity, status_verb


def _ws(slug="w"):
    org = Org.objects.create(name="Acme", slug=f"acme-{slug}")
    return Workspace.objects.create(org=org, name="W", slug=slug)


@pytest.mark.django_db
def test_record_activity_derives_target_fields():
    ws = _ws()
    a = create_area(ws, "Backend")
    s = create_slice(a, "결제 도입", status="idea")
    ActivityEvent.objects.all().delete()  # ignore the create_slice event from Task 2
    record_activity(ws, actor="agent", verb="status_changed", target=s, from_value="idea", to_value="building")
    e = ActivityEvent.objects.get()
    assert e.workspace_id == ws.id
    assert e.actor == "agent" and e.verb == "status_changed"
    assert e.target_type == "slice" and e.target_id == s.id
    assert e.target_label == "결제 도입"
    assert e.from_value == "idea" and e.to_value == "building"


@pytest.mark.django_db
def test_record_activity_survives_target_deletion():
    ws = _ws("w2")
    a = create_area(ws, "Backend")
    s = create_slice(a, "삭제될 것")
    ActivityEvent.objects.all().delete()
    record_activity(ws, actor="human", verb="created", target=s)
    s.delete()
    e = ActivityEvent.objects.get()   # log row still there
    assert e.target_label == "삭제될 것" and e.target_id is not None


def test_status_verb_maps_terminal_states():
    assert status_verb("shipped") == "shipped"
    assert status_verb("dropped") == "dropped"
    assert status_verb("building") == "status_changed"
    assert status_verb("done") == "status_changed"
