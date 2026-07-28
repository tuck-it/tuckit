import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import (
    add_bites,
    bite_progress,
    create_bite,
    list_bites,
    reorder_bite,
    set_bite_status,
    update_bite,
)
from tuckit.core.services.slices import create_slice


@pytest.fixture
def slice_(db):
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    return create_slice(area.org, area=area, title="Auth")


@pytest.mark.django_db
def test_create_bite_defaults_and_order(slice_):
    a = create_bite(slice_, "JWT")
    b = create_bite(slice_, "Social login")
    assert a.status == "todo"
    assert list(list_bites(slice_)) == [a, b]
    assert a.rank < b.rank


@pytest.mark.django_db
def test_create_bite_after_inserts_between(slice_):
    a = create_bite(slice_, "A")
    c = create_bite(slice_, "C")
    b = create_bite(slice_, "B", after=a)
    assert list(list_bites(slice_)) == [a, b, c]


@pytest.mark.django_db
def test_update_and_status(slice_):
    b = create_bite(slice_, "JWT")
    update_bite(b, title="JWT issue", body="use RS256")
    set_bite_status(b, "done")
    b.refresh_from_db()
    assert b.title == "JWT issue"
    assert b.body == "use RS256"
    assert b.status == "done"


@pytest.mark.django_db
def test_reorder_bite_to_front(slice_):
    a = create_bite(slice_, "A")
    b = create_bite(slice_, "B")
    reorder_bite(b, before=a)
    assert list(list_bites(slice_)) == [b, a]


@pytest.mark.django_db
def test_reorder_bite_is_scoped_to_its_own_slice(slice_):
    """reorder_bite must rank a bite among ALL of its slice's siblings, not
    just the ones sharing its own `plan` value.

    A slice can mix a legacy plan-having bite (rows migration 0045 reparented
    onto the slice while leaving Bite.plan populated) with plan-less ones. The
    column survives until 0047 drops it, so the mix is real production data.
    Scoping the rank lookup by `{"plan": bite.plan}` instead of
    `{"slice": bite.slice}` silently drops the plan-having sibling from the
    neighbor search.

    Concretely: A(plan=P, rank a0), B(plan=None, rank a1), C(plan=None, rank
    a2); reorder(C, before=B). The buggy plan-scoped lookup only sees {B, C}
    (A is excluded — different plan), finds no rank below B's, and hands back
    a fresh rank that collides with A's ("a0" == "a0") — a duplicate rank,
    undefined order on Postgres. The fix scopes by slice, sees A too, and
    lands C strictly between A and B.

    Title-order assertions cannot tell these apart (reorder_bite only ever
    touches C's own row), so this asserts on the actual rank values."""
    from tuckit.core.models import Plan

    plan = Plan.objects.create(slice=slice_, title="P")
    a = create_bite(slice_, "A")             # rank a0
    a.plan = plan
    a.save(update_fields=["plan"])
    b = create_bite(slice_, "B")             # rank a1, plan=None
    c = create_bite(slice_, "C")             # rank a2, plan=None

    reorder_bite(c, before=b)

    a.refresh_from_db(); b.refresh_from_db(); c.refresh_from_db()
    assert a.rank < c.rank < b.rank, (a.rank, c.rank, b.rank)


@pytest.mark.django_db
def test_delete_bite_removes_it(slice_):
    from tuckit.core.services.bites import delete_bite
    a = create_bite(slice_, "A")
    b = create_bite(slice_, "B")
    delete_bite(a)
    assert list(list_bites(slice_)) == [b]


@pytest.mark.django_db
def test_bite_progress_counts_done_over_non_dropped():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "A")
    s = create_slice(area.org, area=area, title="S")
    create_bite(s, "a", status="done")
    create_bite(s, "b", status="todo")
    create_bite(s, "c", status="dropped")
    assert bite_progress(s) == (1, 2)


@pytest.mark.django_db
def test_list_bites_and_slice_bites_agree(slice_):
    """slice_bites is the same query as list_bites now that bites hang
    directly off the Slice — both names have to keep working and agree."""
    from tuckit.core.services.bites import slice_bites

    a = create_bite(slice_, "b1")
    b = create_bite(slice_, "b2")
    assert list(list_bites(slice_)) == [a, b]
    assert list(slice_bites(slice_)) == [a, b]


@pytest.mark.django_db
def test_add_bites_bulk_keeps_order(slice_):
    made = add_bites(slice_, [{"title": "one"}, {"title": "two"}, {"title": "three"}])
    assert [b.title for b in made] == ["one", "two", "three"]
    assert [b.title for b in list_bites(slice_)] == ["one", "two", "three"]


# --- Task 5: Bite attaches directly to a Slice, no Plan required ---


@pytest.mark.django_db
def test_bite_attaches_directly_to_a_slice(slice_):
    b = create_bite(slice_, "First step")
    assert b.slice_id == slice_.id
    assert list(list_bites(slice_)) == [b]


@pytest.mark.django_db
def test_add_bites_needs_no_plan(slice_):
    made = add_bites(slice_, [{"title": "a"}, {"title": "b"}], source="agent")
    assert [b.title for b in made] == ["a", "b"]
    assert all(b.slice_id == slice_.id for b in made)


@pytest.mark.django_db
def test_bite_on_an_inbox_slice_is_allowed_by_the_service(org):
    """The service does not block this — hiding steps on an Inbox slice is the
    screen's job. Blocking it in the service would close off a path agents
    legitimately use."""
    from tuckit.core.models import Slice
    s = Slice.objects.create(org=org, area=None, title="unfiled", rank="m", number=1)
    assert create_bite(s, "step").slice_id == s.id
