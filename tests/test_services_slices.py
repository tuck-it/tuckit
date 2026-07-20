import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import (
    create_slice,
    list_slices,
    reorder_slice,
    set_slice_area,
    set_slice_status,
    update_slice,
)


@pytest.fixture
def area(db):
    org = Org.objects.create(name="Acme", slug="acme")
    return create_area(org, "Backend")


@pytest.mark.django_db
def test_create_slice_defaults_and_append_order(area):
    a = create_slice(area, "Auth")
    b = create_slice(area, "Payments")
    assert a.status == "idea"
    assert list(list_slices(area)) == [a, b]
    assert a.rank < b.rank


@pytest.mark.django_db
def test_create_slice_with_tags_and_agent_source(area):
    s = create_slice(area, "Fix XSS", tags=["bug"], source="agent", status="planned")
    assert s.source == "agent"
    assert {t.name for t in s.tags.all()} == {"bug"}


@pytest.mark.django_db
def test_create_slice_after_inserts_between(area):
    a = create_slice(area, "A")
    c = create_slice(area, "C")
    b = create_slice(area, "B", after=a)
    assert list(list_slices(area)) == [a, b, c]


@pytest.mark.django_db
def test_list_slices_filters_by_status_and_tag(area):
    create_slice(area, "Idea one")
    planned = create_slice(area, "Planned bug", status="planned", tags=["bug"])
    assert list(list_slices(area, status="planned")) == [planned]
    assert list(list_slices(area, tag="bug")) == [planned]


@pytest.mark.django_db
def test_set_status_shipped_sets_completed_at(area):
    s = create_slice(area, "Auth")
    set_slice_status(s, "shipped")
    s.refresh_from_db()
    assert s.status == "shipped"
    assert s.completed_at is not None
    set_slice_status(s, "building")
    s.refresh_from_db()
    assert s.completed_at is None


@pytest.mark.django_db
def test_update_slice_replaces_tags(area):
    s = create_slice(area, "Auth", tags=["bug"])
    update_slice(s, title="Auth v2", tags=["chore"])
    s.refresh_from_db()
    assert s.title == "Auth v2"
    assert {t.name for t in s.tags.all()} == {"chore"}


@pytest.mark.django_db
def test_reorder_slice_moves_to_front(area):
    a = create_slice(area, "A")
    b = create_slice(area, "B")
    reorder_slice(b, before=a)
    assert list(list_slices(area)) == [b, a]


@pytest.mark.django_db
def test_create_slice_before_inserts_between(area):
    a = create_slice(area, "A")
    c = create_slice(area, "C")
    b = create_slice(area, "B", before=c)
    assert list(list_slices(area)) == [a, b, c]


@pytest.mark.django_db
def test_slice_tags_never_leak_across_orgs(area):
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_area = create_area(other_org, "Backend")
    s1 = create_slice(area, "One", tags=["bug"])
    s2 = create_slice(other_area, "Two", tags=["bug"])
    tag1 = s1.tags.get()
    tag2 = s2.tags.get()
    assert tag1.id != tag2.id
    assert tag1.org == area.org
    assert tag2.org == other_org


@pytest.mark.django_db
def test_set_slice_area_moves_and_reranks():
    org = Org.objects.create(name="Acme", slug="acme")
    inbox = create_area(org, "Inbox")
    backend = create_area(org, "Backend")
    s = create_slice(inbox, "captured thing")
    set_slice_area(s, backend)
    s.refresh_from_db()
    assert s.area_id == backend.id
    assert list(list_slices(backend)) == [s]
    assert list(list_slices(inbox)) == []


@pytest.mark.django_db
def test_create_slice_allocates_sequential_number_per_org():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s1 = create_slice(a, "One")
    s2 = create_slice(a, "Two")
    assert (s1.number, s2.number) == (1, 2)
    org.refresh_from_db()
    assert org.next_slice_number == 3


@pytest.mark.django_db
def test_number_is_per_org_not_global():
    o1 = Org.objects.create(name="A", slug="a")
    o2 = Org.objects.create(name="B", slug="b")
    s1 = create_slice(create_area(o1, "X"), "s")
    s2 = create_slice(create_area(o2, "Y"), "s")
    assert s1.number == 1 and s2.number == 1


@pytest.mark.django_db
def test_update_slice_assign_by_email_and_clear():
    from django.contrib.auth import get_user_model
    from tuckit.core.models import OrgMember
    from tuckit.core.services.members import resolve_member

    org = Org.objects.create(name="Acme", slug="acme")
    u = get_user_model().objects.create_user(email="a@b.co", password="pw123456")
    m = OrgMember.objects.create(user=u, org=org, role="member")
    s = create_slice(create_area(org, "B"), "Auth")

    update_slice(s, assignee="a@b.co", assignee_member=resolve_member(org, "a@b.co"))
    s.refresh_from_db()
    assert s.assignee_id == m.id

    update_slice(s, assignee="", assignee_member=resolve_member(org, ""))
    s.refresh_from_db()
    assert s.assignee_id is None
