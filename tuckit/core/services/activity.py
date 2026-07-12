from tuckit.core.models import ActivityEvent

_TARGET_TYPES = {"Slice": "slice", "Bite": "bite", "Area": "area"}


def record_activity(workspace, *, actor, verb, target, from_value="", to_value=""):
    """Append one immutable activity row. Denormalizes target label so the log
    survives the target being deleted/dropped."""
    label = getattr(target, "title", None) or getattr(target, "name", "")
    try:
        target_type = _TARGET_TYPES[type(target).__name__]
    except KeyError:
        raise ValueError(f"unsupported activity target: {type(target).__name__}")
    ActivityEvent.objects.create(
        workspace=workspace,
        actor=actor,
        verb=verb,
        target_type=target_type,
        target_id=target.id,
        target_label=(label or "")[:300],
        from_value=from_value or "",
        to_value=to_value or "",
    )


def status_verb(to_status: str) -> str:
    """The verb to record for a status change — terminal states get their own."""
    return {"shipped": "shipped", "dropped": "dropped"}.get(to_status, "status_changed")
