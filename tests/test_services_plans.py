import pytest

from tuckit.core.models import ActivityEvent, Plan
from tuckit.core.services.areas import create_area
from tuckit.core.services.plans import create_plan, get_plan, list_plans, update_plan
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_create_plan_logs_activity(workspace):
    s = create_slice(create_area(workspace, "B"), "S")
    assert get_plan(s) is None

    p = create_plan(s, title="Backend", body="v1", constraints="no billing", actor="agent")
    assert p.title == "Backend" and p.body == "v1" and p.constraints == "no billing"
    assert Plan.objects.count() == 1
    assert ActivityEvent.objects.filter(
        target_type="slice", target_id=s.id, verb="planned"
    ).count() == 1


@pytest.mark.django_db
def test_update_plan_changes_fields_and_logs_only_on_real_change(workspace):
    s = create_slice(create_area(workspace, "B"), "S")
    p = create_plan(s, body="v1", constraints="no billing", actor="agent")
    assert ActivityEvent.objects.filter(
        target_type="slice", target_id=s.id, verb="planned"
    ).count() == 1

    update_plan(p, body="v2")
    p.refresh_from_db()
    assert p.body == "v2" and p.constraints == "no billing"
    assert ActivityEvent.objects.filter(
        target_type="slice", target_id=s.id, verb="planned"
    ).count() == 2

    # no-op update (same value) does not log again
    update_plan(p, body="v2")
    assert ActivityEvent.objects.filter(
        target_type="slice", target_id=s.id, verb="planned"
    ).count() == 2


@pytest.mark.django_db
def test_list_plans_returns_them_in_order(workspace):
    s = create_slice(create_area(workspace, "B"), "S")
    p1 = create_plan(s, title="Backend")
    p2 = create_plan(s, title="UI")
    assert list(list_plans(s)) == [p1, p2]
