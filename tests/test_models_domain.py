import pytest
from django.db import IntegrityError

from tuckit.core.models import Area, Bite, Plan, Slice, Tag


@pytest.mark.django_db
def test_area_slug_unique_per_org(org):
    Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")
    with pytest.raises(IntegrityError):
        Area.objects.create(org=org, name="Backend2", slug="backend", rank="a1")


@pytest.mark.django_db
def test_slice_defaults(org):
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")
    s = Slice.objects.create(area=area, org=org, title="Auth", rank="a0")
    assert s.status == "planned"
    assert s.spec == ""
    assert s.source == "human"
    assert s.completed_at is None


@pytest.mark.django_db
def test_slice_tags_are_org_tags(org):
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")
    s = Slice.objects.create(area=area, org=org, title="Auth", rank="a0")
    tag = Tag.objects.create(org=org, name="bug")
    s.tags.add(tag)
    assert list(s.tags.all()) == [tag]


@pytest.mark.django_db
def test_tag_unique_per_org(org):
    Tag.objects.create(org=org, name="bug")
    with pytest.raises(IntegrityError):
        Tag.objects.create(org=org, name="bug")


@pytest.mark.django_db
def test_bite_requires_plan(org):
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")
    s = Slice.objects.create(area=area, org=org, title="Auth", rank="a0")
    p = Plan.objects.create(slice=s, title="Plan")
    b = Bite.objects.create(plan=p, title="JWT", rank="a0")
    assert b.status == "todo"
    assert b.plan_id == p.id


@pytest.mark.django_db
def test_ticket_number_unique_per_org(org):
    from tuckit.core.models import Ticket
    Ticket.objects.create(org=org, title="A", rank="a0", number=5)
    with pytest.raises(IntegrityError):
        Ticket.objects.create(org=org, title="B", rank="a1", number=5)


@pytest.mark.django_db
def test_ticket_number_null_is_not_deduped(org):
    """The uniqueness is conditional — unnumbered rows must not collide."""
    from tuckit.core.models import Ticket
    Ticket.objects.create(org=org, title="A", rank="a0", number=None)
    Ticket.objects.create(org=org, title="B", rank="a1", number=None)


@pytest.mark.django_db
def test_ticket_external_key_unique_per_org_but_blank_is_free(org):
    from tuckit.core.models import Ticket
    Ticket.objects.create(org=org, title="A", rank="a0", number=1, external_key="todo:1")
    with pytest.raises(IntegrityError):
        Ticket.objects.create(org=org, title="B", rank="a1", number=2, external_key="todo:1")


@pytest.mark.django_db
def test_ticket_blank_external_keys_do_not_collide(org):
    from tuckit.core.models import Ticket
    Ticket.objects.create(org=org, title="A", rank="a0", number=1)
    Ticket.objects.create(org=org, title="B", rank="a1", number=2)


@pytest.mark.django_db
def test_ticket_open_cannot_carry_a_resolved_at(org):
    from django.utils import timezone
    from tuckit.core.models import Ticket
    with pytest.raises(IntegrityError):
        Ticket.objects.create(org=org, title="A", rank="a0", number=1,
                              status="open", resolved_at=timezone.now())


@pytest.mark.django_db
def test_ticket_resolved_requires_a_resolved_at(org):
    from tuckit.core.models import Ticket
    with pytest.raises(IntegrityError):
        Ticket.objects.create(org=org, title="A", rank="a0", number=1,
                              status="dismissed", resolved_at=None)


@pytest.mark.django_db
def test_ticket_status_whitelist_is_enforced_in_the_db(org):
    """The check constraint doubles as a status whitelist — `choices` alone
    never reaches the DB, so raw writes could store anything."""
    from tuckit.core.models import Ticket
    with pytest.raises(IntegrityError):
        Ticket.objects.create(org=org, title="A", rank="a0", number=1, status="closed")


def test_slice_status_choices_are_decisions_only():
    """status는 사람이 내리는 결정만 담는다. 'building'은 관찰이고,
    stage가 파생하므로 여기 있으면 안 된다 (A0)."""
    values = [v for v, _label in Slice.STATUS_CHOICES]
    assert values == ["open", "shipped", "dropped"]


def test_slice_status_defaults_to_open():
    assert Slice._meta.get_field("status").default == "open"
