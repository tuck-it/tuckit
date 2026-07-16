from tuckit.core.models import Plan
from tuckit.core.services.activity import record_activity


def get_plan(slice_):
    return Plan.objects.filter(slice=slice_).first()


def set_plan(slice_, *, body=None, constraints=None, actor="human"):
    """Get-or-create the slice's single Plan, update the given fields, and log a
    `planned` activity when anything changed. Re-plan overwrites in place."""
    plan, changed = Plan.objects.get_or_create(slice=slice_, defaults={"source": actor})
    if body is not None and body != plan.body:
        plan.body = body
        changed = True
    if constraints is not None and constraints != plan.constraints:
        plan.constraints = constraints
        changed = True
    if changed:
        plan.save()
        record_activity(slice_.area.workspace, actor=actor, verb="planned", target=slice_)
    return plan
