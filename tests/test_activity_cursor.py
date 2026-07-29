import pytest
from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.activity import latest_activity_id, events_since


def _org(slug="c"):
    return Org.objects.create(name="Acme", slug=f"acme-{slug}")


@pytest.mark.django_db
def test_latest_activity_id_zero_when_empty():
    org = _org("empty")
    assert latest_activity_id(org) == 0


@pytest.mark.django_db
def test_latest_activity_id_tracks_newest_event():
    org = _org("track")
    create_slice(org, area=create_area(org, "Backend"), title="S1", status="open")
    first = latest_activity_id(org)
    assert first > 0
    create_slice(org, area=create_area(org, "Frontend"), title="S2", status="open")
    assert latest_activity_id(org) > first


@pytest.mark.django_db
def test_events_since_returns_only_newer_ascending():
    org = _org("since")
    create_slice(org, area=create_area(org, "A"), title="S1", status="open")
    cursor = latest_activity_id(org)
    create_slice(org, area=create_area(org, "B"), title="S2", status="open")
    events = events_since(org, cursor)
    assert [e.id for e in events] == sorted(e.id for e in events)
    assert all(e.id > cursor for e in events)
    assert len(events) >= 1


@pytest.mark.django_db
def test_events_since_is_org_scoped():
    org1, org2 = _org("o1"), _org("o2")
    create_slice(org1, area=create_area(org1, "A"), title="S1", status="open")
    create_slice(org2, area=create_area(org2, "B"), title="S2", status="open")
    ev = events_since(org1, 0)
    assert {e.org_id for e in ev} == {org1.id}
