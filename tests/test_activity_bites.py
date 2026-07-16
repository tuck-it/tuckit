import pytest
from tuckit.core.models import ActivityEvent, Org, Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite, set_bite_status, update_bite
from tuckit.core.services.plans import create_plan


def _ws(slug="w"):
    org = Org.objects.create(name="Acme", slug=f"acme-{slug}")
    return Workspace.objects.create(org=org, name="W", slug=slug)


def _slice(ws):
    return create_slice(create_area(ws, "Backend"), "S", status="building")


def _plan(ws):
    return create_plan(_slice(ws), title="Plan")


@pytest.mark.django_db
def test_create_bite_records_created():
    ws = _ws()
    create_bite(_plan(ws), "구현", status="todo", source="agent")
    e = ActivityEvent.objects.get(verb="created", target_type="bite")
    assert e.actor == "agent" and e.target_label == "구현"


@pytest.mark.django_db
def test_set_bite_status_records_transition_with_actor():
    ws = _ws("w2")
    b = create_bite(_plan(ws), "구현", status="todo")
    ActivityEvent.objects.all().delete()
    set_bite_status(b, "doing", actor="human")
    e = ActivityEvent.objects.get()
    assert e.target_type == "bite" and e.verb == "status_changed"
    assert e.from_value == "todo" and e.to_value == "doing" and e.actor == "human"


@pytest.mark.django_db
def test_bite_status_noop_records_nothing():
    ws = _ws("w3")
    b = create_bite(_plan(ws), "구현", status="doing")
    ActivityEvent.objects.all().delete()
    set_bite_status(b, "doing")
    assert ActivityEvent.objects.count() == 0


@pytest.mark.django_db
def test_agent_status_change_records_agent_actor():
    from tuckit.core.services.slices import set_slice_status
    ws = _ws("w4")
    s = _slice(ws)
    ActivityEvent.objects.all().delete()
    set_slice_status(s, "shipped", actor="agent")   # how MCP calls it
    assert ActivityEvent.objects.get().actor == "agent"
