import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import (
    bite_progress,
    create_bite,
    list_bites,
    reorder_bite,
    set_bite_status,
    update_bite,
)
from tuckit.core.services.plans import create_plan
from tuckit.core.services.slices import create_slice


@pytest.fixture
def slice_(db):
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    return create_slice(area, "Auth")


@pytest.fixture
def plan_(slice_):
    return create_plan(slice_, title="Plan")


@pytest.mark.django_db
def test_create_bite_defaults_and_order(plan_):
    a = create_bite(plan_, "JWT")
    b = create_bite(plan_, "Social login")
    assert a.status == "todo"
    assert list(list_bites(plan_)) == [a, b]
    assert a.rank < b.rank


@pytest.mark.django_db
def test_create_bite_after_inserts_between(plan_):
    a = create_bite(plan_, "A")
    c = create_bite(plan_, "C")
    b = create_bite(plan_, "B", after=a)
    assert list(list_bites(plan_)) == [a, b, c]


@pytest.mark.django_db
def test_update_and_status(plan_):
    b = create_bite(plan_, "JWT")
    update_bite(b, title="JWT issue", body="use RS256")
    set_bite_status(b, "done")
    b.refresh_from_db()
    assert b.title == "JWT issue"
    assert b.body == "use RS256"
    assert b.status == "done"


@pytest.mark.django_db
def test_reorder_bite_to_front(plan_):
    a = create_bite(plan_, "A")
    b = create_bite(plan_, "B")
    reorder_bite(b, before=a)
    assert list(list_bites(plan_)) == [b, a]


@pytest.mark.django_db
def test_delete_bite_removes_it(plan_):
    from tuckit.core.services.bites import delete_bite
    a = create_bite(plan_, "A")
    b = create_bite(plan_, "B")
    delete_bite(a)
    assert list(list_bites(plan_)) == [b]


@pytest.mark.django_db
def test_bite_progress_counts_done_over_non_dropped():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "A")
    s = create_slice(area, "S")
    p = create_plan(s, title="Plan")
    create_bite(p, "a", status="done")
    create_bite(p, "b", status="todo")
    create_bite(p, "c", status="dropped")
    assert bite_progress(s) == (1, 2)


@pytest.mark.django_db
def test_bite_belongs_to_plan_and_slice_bites_aggregates(slice_):
    from tuckit.core.services.plans import create_plan
    from tuckit.core.services.bites import slice_bites

    p1 = create_plan(slice_, title="A")
    p2 = create_plan(slice_, title="B")
    create_bite(p1, "b1")
    create_bite(p2, "b2")
    assert [b.title for b in list_bites(p1)] == ["b1"]
    assert {b.title for b in slice_bites(slice_)} == {"b1", "b2"}


@pytest.mark.django_db
def test_add_bites_bulk_keeps_order(slice_):
    from tuckit.core.services.bites import add_bites

    p = create_plan(slice_, title="Plan")
    made = add_bites(p, [{"title": "one"}, {"title": "two"}, {"title": "three"}])
    assert [b.title for b in made] == ["one", "two", "three"]
    assert [b.title for b in list_bites(p)] == ["one", "two", "three"]
