"""Migration tests for 0031_convert_idea_slices — the one-way, run-once backlog
conversion that ships with 0030→0031→0032 and runs for the first time against
the production DB (which still has `idea`-status Slices and `is_triage=True`
Areas). These restore the conversion contract that the deleted Task-6 service
tests encoded, exercised through historical models the way 0031 itself runs.

Mirrors the MigrationExecutor pattern in test_migration_backfill.py /
test_migration_0022_dedup.py: seed the pre-0031 shape via historical models at
the `0030_ticket` state, migrate to `0031_convert_idea_slices`, then assert
through historical models at the `0031` state.
"""

import datetime

import pytest

from tests.migration_utils import at, forward, leave_migrated


@pytest.mark.django_db(transaction=True)
def test_0031_converts_planless_idea_slice_in_triage_to_area_less_ticket():
    old = at(("core", "0030_ticket"))

    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")
    Slice = old.get_model("core", "Slice")
    ActivityEvent = old.get_model("core", "ActivityEvent")

    org = Org.objects.create(name="Acme", slug="acme")
    triage = Area.objects.create(
        org=org, name="Triage", slug="triage", rank="a0", is_triage=True,
    )
    created = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    s = Slice.objects.create(
        area=triage, title="Loose idea", spec="raw spec body",
        status="idea", rank="m", number=7, source="human",
    )
    Slice.objects.filter(pk=s.pk).update(created_at=created)
    ActivityEvent.objects.create(
        org=org, actor="human", verb="created", target_type="slice",
        target_id=s.id, target_label="Loose idea",
    )
    slice_id = s.id

    new = forward(("core", "0031_convert_idea_slices"))

    Slice = new.get_model("core", "Slice")
    Ticket = new.get_model("core", "Ticket")
    ActivityEvent = new.get_model("core", "ActivityEvent")

    assert not Slice.objects.filter(pk=slice_id).exists()  # source slice gone
    t = Ticket.objects.get(org_id=org.id)
    assert t.number == 7                    # number reused
    assert t.body == "raw spec body"        # spec -> body
    assert t.title == "Loose idea"
    assert t.status == "open"
    assert t.area_id is None                 # triage source -> area-less ticket
    assert t.created_at == created           # created_at preserved
    # The slice's activity rows are dropped.
    assert not ActivityEvent.objects.filter(target_type="slice", target_id=slice_id).exists()

    # Leave the DB migrated forward for the rest of the suite.
    leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_0031_keeps_idea_slice_with_plan_as_planned_no_ticket():
    old = at(("core", "0030_ticket"))

    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")
    Slice = old.get_model("core", "Slice")
    Plan = old.get_model("core", "Plan")

    org = Org.objects.create(name="Beta", slug="beta")
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="a0", is_triage=False)
    s = Slice.objects.create(
        area=area, title="Has a plan", spec="", status="idea", rank="m", number=4,
    )
    Plan.objects.create(slice=s, title="Do the thing")
    slice_id = s.id

    new = forward(("core", "0031_convert_idea_slices"))

    Slice = new.get_model("core", "Slice")
    Ticket = new.get_model("core", "Ticket")

    s = Slice.objects.get(pk=slice_id)       # slice survives
    assert s.status == "planned"             # promoted idea -> planned
    assert Ticket.objects.filter(org_id=org.id).count() == 0  # no ticket created

    leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_0031_demotes_triage_area_to_general():
    old = at(("core", "0030_ticket"))

    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")

    org = Org.objects.create(name="Gamma", slug="gamma")
    triage = Area.objects.create(
        org=org, name="Triage", slug="triage", rank="a0", is_triage=True,
    )
    area_id = triage.id

    new = forward(("core", "0031_convert_idea_slices"))

    Area = new.get_model("core", "Area")
    a = Area.objects.get(pk=area_id)
    assert a.is_triage is False              # demoted
    assert a.name == "General"               # "Triage" renamed to "General"

    leave_migrated()
