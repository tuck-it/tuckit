from tuckit.core.models import Plan
from tuckit.core.services.activity import record_activity


def list_plans(slice_):
    return Plan.objects.filter(slice=slice_).order_by("id")


def get_plan(slice_):
    return list_plans(slice_).first()


def create_plan(slice_, *, title="", body="", constraints="", actor="human"):
    plan = Plan.objects.create(slice=slice_, title=title, body=body, constraints=constraints, source=actor)
    record_activity(slice_.area.workspace, actor=actor, verb="planned", target=slice_)
    return plan


def update_plan(plan, *, title=None, body=None, constraints=None, actor="human"):
    changed = False
    for field, value in (("title", title), ("body", body), ("constraints", constraints)):
        if value is not None and value != getattr(plan, field):
            setattr(plan, field, value)
            changed = True
    if changed:
        plan.save()
        record_activity(plan.slice.area.workspace, actor=actor, verb="planned", target=plan.slice)
    return plan


def ensure_default_plan(slice_, actor="agent"):
    return get_plan(slice_) or create_plan(slice_, title="Plan", actor=actor)
