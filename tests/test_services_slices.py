import pytest

from core.models import Org, Workspace
from core.services.areas import create_area
from core.services.slices import (
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
    ws = Workspace.objects.create(org=org, name="P", slug="p")
    return create_area(ws, "Backend")


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
def test_slice_tags_never_leak_across_workspaces(area):
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_ws = Workspace.objects.create(org=other_org, name="Other", slug="other")
    other_area = create_area(other_ws, "Backend")
    s1 = create_slice(area, "One", tags=["bug"])
    s2 = create_slice(other_area, "Two", tags=["bug"])
    tag1 = s1.tags.get()
    tag2 = s2.tags.get()
    assert tag1.id != tag2.id
    assert tag1.workspace == area.workspace
    assert tag2.workspace == other_ws


@pytest.mark.django_db
def test_set_slice_area_moves_and_reranks():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    inbox = create_area(ws, "Inbox")
    backend = create_area(ws, "Backend")
    s = create_slice(inbox, "captured thing")
    set_slice_area(s, backend)
    s.refresh_from_db()
    assert s.area_id == backend.id
    assert list(list_slices(backend)) == [s]
    assert list(list_slices(inbox)) == []
