import pytest
from django.db import IntegrityError

from tuckit.core.models import Area, Bite, Slice, Tag


@pytest.mark.django_db
def test_area_slug_unique_per_org(org):
    Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")
    with pytest.raises(IntegrityError):
        Area.objects.create(org=org, name="Backend2", slug="backend", rank="a1")


@pytest.mark.django_db
def test_slice_defaults(org):
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")
    s = Slice.objects.create(area=area, org=org, title="Auth", rank="a0")
    assert s.status == "open"
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
def test_bite_hangs_off_a_slice(org):
    """There is no Plan to hang off any more — 0050 dropped the table and the
    Bite.plan column with it, so a Slice is the only parent a step can have."""
    area = Area.objects.create(org=org, name="Backend", slug="backend", rank="a0")
    s = Slice.objects.create(area=area, org=org, title="Auth", rank="a0")
    b = Bite.objects.create(slice=s, title="JWT", rank="a0")
    assert b.status == "todo"
    assert b.slice_id == s.id


def test_bite_has_no_plan_column_left():
    """The column drop is the point of 0050: while it existed it was
    on_delete=CASCADE, so deleting a Plan row destroyed a Slice's own steps.
    A field-level assertion, because a row-level one would pass just as well
    against a nullable column nobody happens to fill."""
    assert not any(f.name == "plan" for f in Bite._meta.get_fields())


# The per-org number constraint used to be asserted against Ticket, which
# carried the same pair of constraints as Slice while both tables shared one
# number space. Ticket is gone; the constraint is not, and get_slice_by_ref()
# resolves with .get(), so a duplicate raises MultipleObjectsReturned in a
# caller that does not catch it.
@pytest.mark.django_db
def test_slice_number_unique_per_org(org):
    Slice.objects.create(org=org, title="A", rank="a0", number=5)
    with pytest.raises(IntegrityError):
        Slice.objects.create(org=org, title="B", rank="a1", number=5)


@pytest.mark.django_db
def test_slice_number_null_is_not_deduped(org):
    """The uniqueness is conditional — unnumbered rows must not collide."""
    Slice.objects.create(org=org, title="A", rank="a0", number=None)
    Slice.objects.create(org=org, title="B", rank="a1", number=None)
    assert Slice.objects.filter(number__isnull=True).count() == 2


def test_slice_status_choices_are_decisions_only():
    """status는 사람이 내리는 결정만 담는다. 'building'은 관찰이고,
    stage가 파생하므로 여기 있으면 안 된다 (A0)."""
    values = [v for v, _label in Slice.STATUS_CHOICES]
    assert values == ["open", "shipped", "dropped"]


def test_slice_status_defaults_to_open():
    assert Slice._meta.get_field("status").default == "open"
