import pytest

from tuckit.core.models import Plan
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_slice_can_have_multiple_plans(workspace):
    s = create_slice(create_area(workspace, "B"), "S")
    p1 = Plan.objects.create(slice=s, title="Backend", body="o1", constraints="c1")
    p2 = Plan.objects.create(slice=s, title="UI", body="o2")
    assert list(s.plans.order_by("id")) == [p1, p2]      # reverse FK manager
    assert p1.title == "Backend" and p2.title == "UI"
