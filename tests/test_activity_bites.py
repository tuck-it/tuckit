import pytest
from tuckit.core.models import ActivityEvent, Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite, set_bite_status, update_bite


def _org(slug="w"):
    return Org.objects.create(name="Acme", slug=f"acme-{slug}")


def _slice(org):
    return create_slice(org, area=create_area(org, "Backend"), title="S", status="open")


@pytest.mark.django_db
def test_create_bite_records_created():
    org = _org()
    create_bite(_slice(org), "Implementation", status="todo", source="agent")
    e = ActivityEvent.objects.get(verb="created", target_type="bite")
    assert e.source == "agent" and e.target_label == "Implementation"


@pytest.mark.django_db
def test_set_bite_status_records_transition_with_source():
    org = _org("w2")
    b = create_bite(_slice(org), "Implementation", status="todo")
    ActivityEvent.objects.all().delete()
    set_bite_status(b, "doing", source="human")
    e = ActivityEvent.objects.get()
    assert e.target_type == "bite" and e.verb == "status_changed"
    assert e.from_value == "todo" and e.to_value == "doing" and e.source == "human"


@pytest.mark.django_db
def test_bite_status_noop_records_nothing():
    org = _org("w3")
    b = create_bite(_slice(org), "Implementation", status="doing")
    ActivityEvent.objects.all().delete()
    set_bite_status(b, "doing")
    assert ActivityEvent.objects.count() == 0


@pytest.mark.django_db
def test_agent_status_change_records_agent_source():
    from tuckit.core.services.slices import set_slice_status
    org = _org("w4")
    s = _slice(org)
    ActivityEvent.objects.all().delete()
    set_slice_status(s, "shipped", source="agent")   # how MCP calls it
    assert ActivityEvent.objects.get().source == "agent"
