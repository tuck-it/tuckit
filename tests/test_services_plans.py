import pytest

from tuckit.core.models import ActivityEvent, Plan
from tuckit.core.services.areas import create_area
from tuckit.core.services.plans import get_plan, set_plan
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_set_plan_creates_updates_and_logs(workspace):
    s = create_slice(create_area(workspace, "B"), "S")
    assert get_plan(s) is None

    p = set_plan(s, body="v1", constraints="no billing", actor="agent")
    assert p.body == "v1" and p.constraints == "no billing"
    assert Plan.objects.count() == 1
    assert ActivityEvent.objects.filter(
        target_type="slice", target_id=s.id, verb="planned"
    ).count() == 1

    # partial update in place — no duplicate Plan, constraints preserved
    set_plan(s, body="v2")
    s.refresh_from_db()
    assert Plan.objects.count() == 1
    assert s.plan.body == "v2" and s.plan.constraints == "no billing"
