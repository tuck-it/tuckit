"""Migration test for 0035_slice_org — backfill correctness across areas and orgs.

Worth testing rather than eyeballing because the backfill is a single UPDATE
with a correlated subquery: if it were wrong it would be uniformly wrong, and
every slice in the deployment would carry someone else's org.

Same MigrationExecutor pattern as test_migration_0033_lifecycle.py: seed the
pre-0035 shape through historical models at the 0034 state, migrate, assert
through historical models afterwards.
"""

import pytest

from tests.migration_utils import at, forward, leave_migrated

BEFORE = ("core", "0034_ticket_constraints")
AFTER = ("core", "0035_slice_org")


def _at(state):
    return at(state)


def _forward():
    return forward(AFTER)


def _leave_migrated():
    """Leave the DB at the leaf for the rest of the suite."""
    leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_backfills_org_across_several_areas_and_orgs():
    old = _at(BEFORE)
    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")
    Slice = old.get_model("core", "Slice")

    o1 = Org.objects.create(name="Acme", slug="acme")
    o2 = Org.objects.create(name="Beta", slug="beta")
    # Two areas in one org, so a per-area backfill bug would show up as a
    # mismatch rather than being masked by a one-area-per-org shape.
    a1 = Area.objects.create(org=o1, name="Backend", slug="backend", rank="m")
    a2 = Area.objects.create(org=o1, name="Frontend", slug="frontend", rank="n")
    b1 = Area.objects.create(org=o2, name="Ops", slug="ops", rank="m")
    Slice.objects.create(area=a1, title="A", rank="m", number=1)
    Slice.objects.create(area=a2, title="B", rank="n", number=2)
    Slice.objects.create(area=b1, title="C", rank="m", number=1)

    new = _forward()
    NewSlice = new.get_model("core", "Slice")
    by_title = {s.title: s for s in NewSlice.objects.all()}
    assert by_title["A"].org_id == o1.id
    assert by_title["B"].org_id == o1.id
    assert by_title["C"].org_id == o2.id

    _leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_number_reuse_across_orgs_survives_the_new_constraint():
    """Slices A and C both hold number 1 in different orgs above. The constraint
    is per-org, so that must migrate cleanly — a per-table-global unique index
    would have failed the AddConstraint step."""
    old = _at(BEFORE)
    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")
    Slice = old.get_model("core", "Slice")

    o1 = Org.objects.create(name="Acme", slug="acme")
    o2 = Org.objects.create(name="Beta", slug="beta")
    Slice.objects.create(
        area=Area.objects.create(org=o1, name="X", slug="x", rank="m"),
        title="A", rank="m", number=5,
    )
    Slice.objects.create(
        area=Area.objects.create(org=o2, name="Y", slug="y", rank="m"),
        title="B", rank="m", number=5,
    )

    new = _forward()
    assert new.get_model("core", "Slice").objects.filter(number=5).count() == 2

    _leave_migrated()
