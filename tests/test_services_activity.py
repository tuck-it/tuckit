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
    s = create_slice(a.org, area=a, title="Payment integration", status="open")
    ActivityEvent.objects.all().delete()  # ignore the create_slice event from Task 2
    record_activity(org, actor="agent", verb="status_changed", target=s, from_value="open", to_value="shipped")
    e = ActivityEvent.objects.get()
    assert e.org_id == org.id
    assert e.actor == "agent" and e.verb == "status_changed"
    assert e.target_type == "slice" and e.target_id == s.id
    assert e.target_label == "Payment integration"
    assert e.from_value == "open" and e.to_value == "shipped"


@pytest.mark.django_db
def test_record_activity_survives_target_deletion():
    org = _org("w2")
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="To be deleted")
    ActivityEvent.objects.all().delete()
    record_activity(org, actor="human", verb="created", target=s)
    s.delete()
    e = ActivityEvent.objects.get()   # log row still there
    assert e.target_label == "To be deleted" and e.target_id is not None


def test_status_verb_maps_terminal_states():
    assert status_verb("shipped") == "shipped"
    assert status_verb("dropped") == "dropped"
    assert status_verb("open") == "status_changed"
    assert status_verb("done") == "status_changed"


@pytest.mark.django_db
def test_add_note_appends_noted_event_with_body():
    from tuckit.core.services.activity import add_note, slice_activity

    org = _org("note")
    s = create_slice(org, area=create_area(org, "B"), title="Auth")
    ev = add_note(s, "Shipped behind flag; see PR #12.", actor="agent")
    assert ev.verb == "noted" and ev.actor == "agent"
    assert ev.body == "Shipped behind flag; see PR #12."
    assert [e.id for e in slice_activity(s)][-1] == ev.id


@pytest.mark.django_db
def test_active_targets_folds_bite_activity_onto_its_slice():
    """A bite is never rendered as its own element on a live screen, so its
    activity belongs to the slice card the viewer can actually see."""
    from tuckit.core.services.activity import active_targets
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.plans import create_plan

    org = Org.objects.create(name="Acme", slug="acme-at1")
    slice_ = create_slice(org, area=create_area(org, "Backend"), title="Login", status="open")
    create_bite(slice_, "Wire the form", source="agent")

    active = active_targets(org)

    assert set(active) == {slice_.id}
    _last_touch, verb, label = active[slice_.id]
    assert verb == "created"
    assert label == "Wire the form"


@pytest.mark.django_db
def test_active_targets_keeps_only_the_most_recent_touch_per_slice():
    from tuckit.core.services.activity import active_targets
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.plans import create_plan

    org = Org.objects.create(name="Acme", slug="acme-at2")
    slice_ = create_slice(org, area=create_area(org, "Backend"), title="Login", status="open")
    create_bite(slice_, "First", source="agent")
    create_bite(slice_, "Second", source="agent")

    _last_touch, _verb, label = active_targets(org)[slice_.id]

    assert label == "Second"


@pytest.mark.django_db
def test_active_targets_excludes_human_activity():
    """Warmth means 'an agent is working here'. A human editing their own board
    must not light it up."""
    from tuckit.core.services.activity import active_targets

    org = Org.objects.create(name="Acme", slug="acme-at3")
    create_slice(org, area=create_area(org, "Backend"), title="Login", status="open")  # source defaults to human

    assert active_targets(org) == {}


@pytest.mark.django_db
def test_active_targets_excludes_activity_older_than_the_window():
    from datetime import timedelta
    from django.utils import timezone
    from tuckit.core.models import ActivityEvent
    from tuckit.core.services.activity import active_targets

    org = Org.objects.create(name="Acme", slug="acme-at4")
    slice_ = create_slice(org, area=create_area(org, "Backend"), title="Login", status="open")
    ActivityEvent.objects.filter(org=org).update(actor="agent")
    ActivityEvent.objects.filter(org=org).update(
        created_at=timezone.now() - timedelta(seconds=600)
    )

    assert active_targets(org, window_seconds=300) == {}
    assert set(active_targets(org, window_seconds=900)) == {slice_.id}


@pytest.mark.django_db
def test_active_targets_is_scoped_to_one_org():
    from tuckit.core.services.activity import active_targets

    org_a = Org.objects.create(name="A", slug="acme-at5a")
    org_b = Org.objects.create(name="B", slug="acme-at5b")
    create_slice(org_b, area=create_area(org_b, "Backend"), title="Login", status="open", source="agent")

    assert active_targets(org_a) == {}


@pytest.mark.django_db
def test_active_targets_skips_a_bite_whose_slice_is_gone():
    """delete_bite records the event and THEN deletes the row, so the parent
    lookup finds nothing. It must be skipped, not raise — a per-event .get()
    here would raise Bite.DoesNotExist and take down every warm card in the org.

    The event is flipped to actor="agent" on purpose: delete_bite hardcodes
    actor="human" (bites.py:102), so without the flip the actor filter would
    drop it and this test would pass GREEN without ever reaching the parent
    lookup it exists to cover."""
    from tuckit.core.models import ActivityEvent
    from tuckit.core.services.activity import active_targets
    from tuckit.core.services.bites import create_bite, delete_bite
    from tuckit.core.services.plans import create_plan

    org = Org.objects.create(name="Acme", slug="acme-at6")
    slice_ = create_slice(org, area=create_area(org, "Backend"), title="Login", status="open")
    bite = create_bite(slice_, "Doomed", source="agent")
    ActivityEvent.objects.filter(org=org).delete()
    delete_bite(bite)
    ActivityEvent.objects.filter(org=org).update(actor="agent")

    assert active_targets(org) == {}
