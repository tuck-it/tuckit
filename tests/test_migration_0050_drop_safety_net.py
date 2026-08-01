"""0050 takes down the safety net without taking history with it.

The destructive half (DROP TABLE, drop column) is checked by the schema itself
— the models no longer declare them and the suite would not boot otherwise.
What needs asserting is the data half: forward() deletes activity rows, and a
delete that reaches one row too far is silent.

Migrator.apply_initial_migration() drops every model table and replays FORWARD
to the target, so these run even though 0045's and 0050's backward() raise.
"""
import pytest
from django_test_migrations.migrator import Migrator

BEFORE = ("core", "0046_schema_repair")
AFTER = ("core", "0050_drop_tickets_and_plans")


@pytest.mark.django_db
def test_activity_pointing_at_a_deleted_ticket_is_removed(migrator: Migrator):
    """These are the rows 0045 explicitly declined to retarget: their ticket
    was already gone when it ran, so there was nothing to point them at. They
    render on no surface — slice_activity() and active_targets() both narrow
    target_type to slice/bite — and 0050 removes 'ticket' from the field's
    choices, so leaving them would strand a value nothing can write or read."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Activity = old.apps.get_model("core", "ActivityEvent")

    org = Org.objects.create(name="O", slug="o", key="O")
    Activity.objects.create(
        org=org, actor="agent", verb="promoted", target_type="ticket",
        target_id=404, target_label="a ticket that was already deleted",
    )

    new = migrator.apply_tested_migration(AFTER)
    NewActivity = new.apps.get_model("core", "ActivityEvent")

    assert not NewActivity.objects.filter(target_type="ticket").exists()


@pytest.mark.django_db
def test_it_deletes_only_the_ticket_typed_rows(migrator: Migrator):
    """The whole activity thread of every slice runs through this table. A
    filter that slipped — or a `.delete()` on the wrong queryset — would erase
    the product's entire history, and nothing downstream would raise: an empty
    thread renders as an empty thread."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Activity = old.apps.get_model("core", "ActivityEvent")

    org = Org.objects.create(name="O", slug="o", key="O")
    Activity.objects.create(org=org, actor="agent", verb="promoted",
                            target_type="ticket", target_id=1, target_label="gone")
    Activity.objects.create(org=org, actor="human", verb="shipped",
                            target_type="slice", target_id=1, target_label="kept slice")
    Activity.objects.create(org=org, actor="agent", verb="created",
                            target_type="bite", target_id=2, target_label="kept bite")
    Activity.objects.create(org=org, actor="human", verb="created",
                            target_type="area", target_id=3, target_label="kept area")

    new = migrator.apply_tested_migration(AFTER)
    NewActivity = new.apps.get_model("core", "ActivityEvent")

    assert sorted(NewActivity.objects.values_list("target_label", flat=True)) == [
        "kept area", "kept bite", "kept slice",
    ]


@pytest.mark.django_db
def test_a_slices_steps_survive_the_plan_column_going_away(migrator: Migrator):
    """Bite.plan was on_delete=CASCADE right up to this migration, which is the
    hazard the whole slice is about: one Plan row taking a Slice's steps with
    it. Dropping the column must not fire that path — the steps belong to the
    slice, and 0045 already reparented them."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Area = old.apps.get_model("core", "Area")
    Slice = old.apps.get_model("core", "Slice")
    Plan = old.apps.get_model("core", "Plan")
    Bite = old.apps.get_model("core", "Bite")

    org = Org.objects.create(name="O", slug="o", key="O")
    area = Area.objects.create(org=org, name="A", slug="a", rank="m")
    s = Slice.objects.create(org=org, area=area, title="work", rank="m", number=1)
    plan = Plan.objects.create(slice=s, title="P")
    # The shape 0045 left behind: reparented onto the slice, plan still set.
    Bite.objects.create(slice=s, plan=plan, title="migrated step", rank="a0")
    Bite.objects.create(slice=s, plan=None, title="direct step", rank="a1")

    new = migrator.apply_tested_migration(AFTER)
    NewBite = new.apps.get_model("core", "Bite")

    assert sorted(NewBite.objects.filter(slice_id=s.id).values_list("title", flat=True)) == [
        "direct step", "migrated step",
    ]


@pytest.mark.django_db
def test_the_tables_are_actually_gone(migrator: Migrator):
    """A DROP that silently did not happen leaves a table nothing reads — which
    is exactly the state this slice exists to end, so it is asserted against
    the database rather than the model layer."""
    from django.db import connection

    migrator.apply_initial_migration(BEFORE)
    with connection.cursor() as c:
        before = connection.introspection.table_names(c)
    assert "core_ticket" in before and "core_plan" in before, before

    migrator.apply_tested_migration(AFTER)
    with connection.cursor() as c:
        after = connection.introspection.table_names(c)
    assert "core_ticket" not in after
    assert "core_plan" not in after
    assert "plan_id" not in [
        f.name for f in connection.introspection.get_table_description(
            connection.cursor(), "core_bite"
        )
    ]
