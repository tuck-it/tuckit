"""Migration test for 0037_clear_copied_specs — surgical, not blanket.

The value of this migration is mostly in what it does NOT touch. A spec someone
edited after promotion is their work; clearing it because it happens to start
with the ticket's text would be data loss dressed up as a cleanup.

Same MigrationExecutor pattern as test_migration_0033_lifecycle.py.
"""

import pytest
from django.utils import timezone

from tests.migration_utils import at, forward, leave_migrated

BEFORE = ("core", "0036_ticket_slice_fk")
AFTER = ("core", "0037_clear_copied_specs")


def _at(state):
    return at(state)


def _forward():
    return forward(AFTER)


def _leave_migrated():
    """Leave the DB at the leaf for the rest of the suite."""
    leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_clears_exact_copies_and_preserves_everything_else():
    old = _at(BEFORE)
    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")
    Slice = old.get_model("core", "Slice")
    Ticket = old.get_model("core", "Ticket")

    org = Org.objects.create(name="Acme", slug="acme")
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="m")

    # 1. verbatim copy -> cleared
    copy = Slice.objects.create(area=area, org=org, title="Copy", rank="a",
                                number=1, spec="the body")
    Ticket.objects.create(org=org, area=area, title="Copy", rank="a", number=1,
                          body="the body", status="promoted", resolved_at=timezone.now(), slice=copy)

    # 2. edited after promotion -> preserved
    edited = Slice.objects.create(area=area, org=org, title="Edited", rank="b",
                                  number=2, spec="the body, plus a real design")
    Ticket.objects.create(org=org, area=area, title="Edited", rank="b", number=2,
                          body="the body", status="promoted", resolved_at=timezone.now(), slice=edited)

    # 3. no linked ticket at all -> preserved
    standalone = Slice.objects.create(area=area, org=org, title="Direct", rank="c",
                                      number=3, spec="hand-written")

    new = _forward()
    NewSlice = new.get_model("core", "Slice")
    assert NewSlice.objects.get(pk=copy.pk).spec == ""
    assert NewSlice.objects.get(pk=edited.pk).spec == "the body, plus a real design"
    assert NewSlice.objects.get(pk=standalone.pk).spec == "hand-written"

    _leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_an_absorbed_ticket_body_does_not_clear_the_spec():
    """Only the ORIGIN's body counts. A slice whose spec happens to match some
    absorbed ticket's body has not been shown to be a promotion artifact."""
    old = _at(BEFORE)
    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")
    Slice = old.get_model("core", "Slice")
    Ticket = old.get_model("core", "Ticket")

    org = Org.objects.create(name="Acme", slug="acme")
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="m")
    s = Slice.objects.create(area=area, org=org, title="S", rank="a", number=1,
                             spec="absorbed text")
    # origin (number matches the slice) has a DIFFERENT body
    Ticket.objects.create(org=org, area=area, title="Origin", rank="a", number=1,
                          body="origin text", status="promoted", resolved_at=timezone.now(), slice=s)
    # absorbed ticket's body matches the spec, but it is not the origin
    Ticket.objects.create(org=org, area=area, title="Absorbed", rank="b", number=2,
                          body="absorbed text", status="promoted", resolved_at=timezone.now(), slice=s)

    new = _forward()
    assert new.get_model("core", "Slice").objects.get(pk=s.pk).spec == "absorbed text"

    _leave_migrated()
