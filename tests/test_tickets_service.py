import pytest

from tuckit.core.models import Org, Ticket, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.refs import ticket_ref
from tuckit.core.services.resolve import get_ticket, get_ticket_by_ref, resolve_ref


@pytest.mark.django_db
def test_ticket_defaults_and_slice_link():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    t = Ticket.objects.create(org=org, area=area, title="Fix login", rank="m")
    assert t.status == "open"
    assert t.source == "human"
    assert t.body == ""
    assert t.closed_at is None
    assert t.created_by is None
    # area-less (Inbox) ticket is allowed
    inbox = Ticket.objects.create(org=org, area=None, title="Stray idea", rank="m")
    assert inbox.area is None
    # Slice can link back to a Ticket
    s = Slice.objects.create(area=area, title="S", rank="m", number=1, ticket=t)
    assert t.slice == s


@pytest.mark.django_db
def test_ref_and_resolution_prefers_slice():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    t = Ticket.objects.create(org=org, area=area, title="T", rank="m", number=42)
    assert ticket_ref(t) == "acme-42"
    assert get_ticket(org, t.id) == t
    assert get_ticket_by_ref(org, "acme-42") == t
    # unpromoted -> ref resolves to the Ticket
    assert resolve_ref(org, "acme-42") == t
    # promote: a Slice inherits number 42 -> ref now resolves to the Slice
    s = Slice.objects.create(area=area, title="S", rank="m", number=42, ticket=t)
    assert resolve_ref(org, "acme-42") == s


from tuckit.core.services.tickets import (
    create_ticket, query_tickets, update_ticket, close_ticket,
)


@pytest.mark.django_db
def test_create_ticket_mints_shared_number_and_defaults_to_inbox():
    org = Org.objects.create(name="Acme", slug="acme")
    t1 = create_ticket(org, "First")
    t2 = create_ticket(org, "Second")
    assert (t1.number, t2.number) == (1, 2)          # shared per-org sequence
    assert t1.area is None and t1.status == "open"    # inbox by default
    org.refresh_from_db()
    assert org.next_slice_number == 3


@pytest.mark.django_db
def test_query_tickets_open_inbox_only():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    open_t = create_ticket(org, "Open")
    closed_t = create_ticket(org, "Closed")
    close_ticket(closed_t)
    # a promoted ticket has a linked slice -> excluded from the raw inbox
    promoted = create_ticket(org, "Promoted")
    Slice.objects.create(area=area, title="S", rank="m", number=promoted.number, ticket=promoted)
    rows = query_tickets(org)
    assert [t.title for t in rows] == ["Open"]


@pytest.mark.django_db
def test_update_and_close_ticket():
    org = Org.objects.create(name="Acme", slug="acme")
    t = create_ticket(org, "T")
    update_ticket(t, title="T2", body="details")
    t.refresh_from_db()
    assert t.title == "T2" and t.body == "details"
    close_ticket(t)
    t.refresh_from_db()
    assert t.status == "closed" and t.closed_at is not None


from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slices import set_slice_status, update_slice
from tuckit.core.services.tickets import promote_ticket


@pytest.mark.django_db
def test_promote_inherits_number_and_links():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    t = create_ticket(org, "Fix login", area=area)
    s = promote_ticket(t)
    assert s.number == t.number          # same ref across promotion
    assert s.status == "planned"
    assert s.ticket_id == t.id
    t.refresh_from_db()
    assert t.status == "open"            # stays open while the Slice is in flight


@pytest.mark.django_db
def test_promote_area_less_ticket_requires_area():
    org = Org.objects.create(name="Acme", slug="acme")
    inbox_t = create_ticket(org, "Stray")   # area=None
    with pytest.raises(InvalidValue):
        promote_ticket(inbox_t)
    area = create_area(org, "Backend")
    s = promote_ticket(inbox_t, area=area)
    assert s.area_id == area.id


@pytest.mark.django_db
def test_shipping_slice_autocloses_ticket():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    t = create_ticket(org, "Fix login", area=area)
    s = promote_ticket(t)
    set_slice_status(s, "shipped")
    t.refresh_from_db()
    assert t.status == "closed" and t.closed_at is not None


from tuckit.core.models import ActivityEvent, Area, Plan
from tuckit.core.services.tickets import convert_org_backlog


@pytest.mark.django_db
def test_convert_backlog_idea_without_plan_becomes_ticket():
    org = Org.objects.create(name="Acme", slug="acme")
    triage = Area.objects.create(org=org, name="Triage", slug="triage", is_triage=True, rank="m")
    s = Slice.objects.create(area=triage, title="Stray", spec="notes", status="idea",
                             rank="m", number=7, source="human")
    ActivityEvent.objects.create(org=org, actor="human", verb="created",
                                 target_type="slice", target_id=s.id, target_label="Stray")
    convert_org_backlog(org)
    assert not Slice.objects.filter(pk=s.id).exists()
    t = Ticket.objects.get(number=7)
    assert t.title == "Stray" and t.body == "notes" and t.area is None
    assert not ActivityEvent.objects.filter(target_type="slice", target_id=s.id).exists()
    triage.refresh_from_db()
    assert triage.is_triage is False and triage.name == "General"


@pytest.mark.django_db
def test_convert_backlog_idea_with_plan_becomes_planned():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = Slice.objects.create(area=area, title="Worked", status="idea", rank="m", number=3)
    Plan.objects.create(slice=s, title="P")
    convert_org_backlog(org)
    s.refresh_from_db()
    assert s.status == "planned"
    assert not Ticket.objects.filter(number=3).exists()
