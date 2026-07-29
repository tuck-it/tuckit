"""Migration tests for 0033_ticket_lifecycle — the open/closed -> open/promoted/
dismissed/duplicate conversion, which runs once against the production DB that
v0.26.0 already populated with open- and closed-status Tickets.

Two things make this worth testing rather than eyeballing: the old `closed`
conflated "shipped as a slice" with "decided against", so the split is inferred
from whether a Slice was ever linked; and 0034 then adds three DB constraints,
so every row must come out of 0033 consistent or the deploy fails mid-migrate.

(The constraints live in 0034 rather than 0033 because Postgres cannot build an
index on a table with pending trigger events from the same transaction. These
tests migrate through both.)

Same MigrationExecutor pattern as test_migration_0031_convert.py: seed the
pre-0033 shape through historical models at the `0032` state, migrate, assert
through historical models afterwards.
"""

import pytest

from tests.migration_utils import at, back, forward, leave_migrated

BEFORE = ("core", "0032_drop_idea_and_is_triage")
AFTER = ("core", "0034_ticket_constraints")


def _at(state):
    return at(state)


def _forward():
    return forward(AFTER)


def _leave_migrated():
    """Leave the DB at the leaf for the rest of the suite."""
    leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_0033_splits_closed_into_promoted_and_dismissed():
    old = _at(BEFORE)
    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")
    Slice = old.get_model("core", "Slice")
    Ticket = old.get_model("core", "Ticket")

    org = Org.objects.create(name="Acme", slug="acme", next_slice_number=10)
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")

    # closed + a linked slice == it became work and reached a terminal state
    shipped = Ticket.objects.create(org=org, title="Shipped one", status="closed",
                                    number=1, rank="a")
    Slice.objects.create(area=area, title="Shipped one", rank="a", number=1, ticket=shipped)
    # closed + no slice == decided against at triage
    wontdo = Ticket.objects.create(org=org, title="Won't do", status="closed",
                                   number=2, rank="b")
    # open + a linked slice == the old ghost state (open, but hidden from the Inbox)
    inflight = Ticket.objects.create(org=org, title="In flight", status="open",
                                     number=3, rank="c")
    Slice.objects.create(area=area, title="In flight", rank="c", number=3, ticket=inflight)
    # open + no slice == still the Inbox
    untouched = Ticket.objects.create(org=org, title="Still open", status="open",
                                      number=4, rank="d")
    ids = (shipped.id, wontdo.id, inflight.id, untouched.id)

    new = _forward()
    Ticket = new.get_model("core", "Ticket")
    got = {t.id: t for t in Ticket.objects.filter(id__in=ids)}

    assert got[shipped.id].status == "promoted"
    assert got[wontdo.id].status == "dismissed"     # no longer indistinguishable
    assert got[inflight.id].status == "promoted"    # ghost state resolved
    assert got[untouched.id].status == "open"

    # The added CheckConstraint requires this pairing to hold for every row.
    assert got[untouched.id].resolved_at is None
    for tid in (shipped.id, wontdo.id, inflight.id):
        assert got[tid].resolved_at is not None

    _leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_0033_repairs_duplicate_numbers_before_enforcing_uniqueness():
    """uniq_ticket_number_per_org is added in this migration; a pre-existing
    collision (admin/import/raw ORM, which never took the number lock) would
    otherwise abort the deploy."""
    old = _at(BEFORE)
    Org = old.get_model("core", "Org")
    Ticket = old.get_model("core", "Ticket")

    org = Org.objects.create(name="Dup", slug="dup", next_slice_number=50)
    first = Ticket.objects.create(org=org, title="First", status="open", number=7, rank="a")
    clash = Ticket.objects.create(org=org, title="Clash", status="open", number=7, rank="b")

    new = _forward()
    Ticket = new.get_model("core", "Ticket")
    kept = Ticket.objects.get(pk=first.id)
    fixed = Ticket.objects.get(pk=clash.id)

    assert kept.number == 7            # earliest ticket keeps the number
    assert fixed.number == 50          # later one gets a fresh one off the org counter
    assert Org.objects.get(pk=org.id).next_slice_number == 51

    _leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_0033_is_reversible():
    old = _at(BEFORE)
    Org = old.get_model("core", "Org")
    Area = old.get_model("core", "Area")
    Slice = old.get_model("core", "Slice")
    Ticket = old.get_model("core", "Ticket")

    org = Org.objects.create(name="Rev", slug="rev", next_slice_number=10)
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")
    promoted = Ticket.objects.create(org=org, title="P", status="open", number=1, rank="a")
    Slice.objects.create(area=area, title="P", rank="a", number=1, ticket=promoted)
    dismissed = Ticket.objects.create(org=org, title="D", status="closed", number=2, rank="b")

    _forward()
    # A genuine unapply, not a wipe-and-replay — that is the whole point here.
    # Safe because the DB sits at 0034, well below the irreversible 0045.
    rolled_back = back(BEFORE)
    Ticket = rolled_back.get_model("core", "Ticket")

    assert Ticket.objects.get(pk=promoted.id).status == "open"
    assert Ticket.objects.get(pk=dismissed.id).status == "closed"

    _leave_migrated()
