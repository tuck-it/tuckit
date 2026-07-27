import pytest
from django.urls import reverse
from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite, delete_bite
from tuckit.core.services.plans import create_plan
from tuckit.core.services.slices import create_slice
from tuckit.core.services.activity import latest_activity_id


@pytest.fixture
def member(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="m@b.co", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    return org, user


@pytest.mark.django_db
def test_live_204_when_nothing_new(client, member):
    org, user = member
    client.force_login(user)
    cursor = latest_activity_id(org)
    resp = client.get(reverse("web:live", args=[org.slug]) + f"?since={cursor}")
    assert resp.status_code == 204


@pytest.mark.django_db
def test_live_returns_new_events_and_cursor(client, member):
    org, user = member
    client.force_login(user)
    cursor = latest_activity_id(org)
    create_slice(org, area=create_area(org, "Backend"), title="Login", status="open")
    resp = client.get(reverse("web:live", args=[org.slug]) + f"?since={cursor}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cursor"] > cursor
    verbs = {e["verb"] for e in data["events"]}
    assert "created" in verbs
    assert all(e["id"] > cursor for e in data["events"])
    # Cursor must be the newest DELIVERED event id (not a max read before the
    # fetch), so the next poll can't re-deliver an event already sent.
    assert data["cursor"] == max(e["id"] for e in data["events"])


@pytest.mark.django_db
def test_live_missing_since_treated_as_zero(client, member):
    org, user = member
    client.force_login(user)
    create_area(org, "Backend")
    resp = client.get(reverse("web:live", args=[org.slug]))
    assert resp.status_code == 200
    assert len(resp.json()["events"]) >= 1


@pytest.mark.django_db
def test_bite_event_carries_its_own_id_and_label(client, member):
    """A bite is never rendered as its own element on a live-refresh screen — it
    shows up as the parent slice's bite progress. That fold now happens
    server-side in active_targets() (which occupancy warmth reads), not in this
    payload — the live endpoint just reports the bite event as itself."""
    org, user = member
    client.force_login(user)
    slice_ = create_slice(org, area=create_area(org, "Backend"), title="Login", status="open")
    create_plan(slice_, title="Plan")
    cursor = latest_activity_id(org)
    bite = create_bite(slice_, "Wire the form", source="agent")

    resp = client.get(reverse("web:live", args=[org.slug]) + f"?since={cursor}")
    event = next(e for e in resp.json()["events"] if e["target_type"] == "bite")

    assert event["target_id"] == bite.id
    assert event["target_label"] == "Wire the form"


@pytest.mark.django_db
def test_deleted_bite_event_still_delivers(client, member):
    """delete_bite records the event and THEN deletes the row. Regression guard
    kept from when the payload resolved a parent slice per-event: a naive
    .get() there would raise on a bite already gone and take the whole poll
    down — one dead bite would stop every toast in the org. The live endpoint
    no longer does that resolution at all, but delivering the deletion event
    itself without erroring is still the behavior worth pinning."""
    org, user = member
    client.force_login(user)
    slice_ = create_slice(org, area=create_area(org, "Backend"), title="Login", status="open")
    bite = create_bite(slice_, "Doomed")
    cursor = latest_activity_id(org)
    delete_bite(bite)

    resp = client.get(reverse("web:live", args=[org.slug]) + f"?since={cursor}")

    assert resp.status_code == 200
    event = next(e for e in resp.json()["events"] if e["target_type"] == "bite")
    assert event["verb"] == "deleted"


@pytest.mark.django_db
def test_live_404_for_non_member(client, member):
    org, _ = member
    other = User.objects.create_user(email="x@b.co", password="pw123456")
    client.force_login(other)
    resp = client.get(reverse("web:live", args=[org.slug]))
    assert resp.status_code == 404
