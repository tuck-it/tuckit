import pytest

from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice, query_slices


@pytest.mark.django_db
def test_priority_outranks_manual_order_and_unset_sorts_last():
    """The failure this pins is invisible on sqlite: Postgres puts NULLs last in
    ASC and sqlite puts them first, so an unranked slice sits at the bottom in
    production and at the top locally. Only an explicit nulls_last is the same
    on both."""
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    create_slice(org, area=area, title="Unranked")
    low = create_slice(org, area=area, title="Low")
    top = create_slice(org, area=area, title="Top")
    Slice.objects.filter(id=low.id).update(priority=4)
    Slice.objects.filter(id=top.id).update(priority=1)

    titles = [s.title for s in query_slices(org, area=area)]

    assert titles == ["Top", "Low", "Unranked"]


@pytest.mark.django_db
def test_rank_still_breaks_ties_inside_one_priority():
    """priority is the primary key, not a replacement: dropping rank would erase
    every hand-made ordering already on the board."""
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    first = create_slice(org, area=area, title="First")
    second = create_slice(org, area=area, title="Second", after=first)
    Slice.objects.filter(id__in=[first.id, second.id]).update(priority=2)

    titles = [s.title for s in query_slices(org, area=area)]

    assert titles == ["First", "Second"]
