from tuckit.core.models import ActivityEvent

_TARGET_TYPES = {"Slice": "slice", "Bite": "bite", "Area": "area"}


def record_activity(org, *, source, verb, target, from_value="", to_value="", body="", member=None):
    """Append one immutable activity row. Denormalizes target label so the log
    survives the target being deleted/dropped.

    `source` is how it arrived (human|agent); `member` is the person, and stays None
    when the caller cannot be identified — a legacy ApiToken has no user behind
    it. Attribution is a capture decision: a row written without a member is
    unattributed forever, so callers should pass one whenever they have one.
    """
    label = getattr(target, "title", None) or getattr(target, "name", "")
    try:
        target_type = _TARGET_TYPES[type(target).__name__]
    except KeyError:
        raise ValueError(f"unsupported activity target: {type(target).__name__}") from None
    return ActivityEvent.objects.create(
        org=org,
        source=source,
        member=member,
        verb=verb,
        target_type=target_type,
        target_id=target.id,
        target_label=(label or "")[:300],
        from_value=from_value or "",
        to_value=to_value or "",
        body=body or "",
    )


def add_note(slice_, body: str, *, source: str = "agent", member=None):
    """Append a free-text note to a slice's activity thread."""
    return record_activity(
        slice_.org, source=source, verb="noted", target=slice_, body=body, member=member
    )


def who_label(event, viewer=None) -> str:
    """How to name the person behind one event, from `viewer`'s seat.

    Viewer-relative on purpose: in a one-person org every row would otherwise
    repeat the same address, which is noise. Saying "you" only when it really
    is you is also what makes a colleague's row legible as theirs.

    `viewer=None` (anonymous, or a caller that did not thread it through)
    degrades to showing the address. That is the safe direction — verbose, but
    it never tells you that someone else's work was yours, which is the bug
    this exists to end.
    """
    who = event.member
    if who is None:
        # Rows written before attribution existed, and machine tokens, which
        # have no user behind them at all. Never "you": that was the bug.
        return "agent" if event.source == "agent" else "someone"
    if viewer is not None and who.pk == viewer.pk:
        return "agent" if event.source == "agent" else "you"
    name = who.user.email
    return f"{name} (agent)" if event.source == "agent" else name


def label_who(events, viewer=None):
    """Stamp `who` on each event for rendering. Returns the same list."""
    for e in events:
        e.who = who_label(e, viewer)
    return events


def status_verb(to_status: str) -> str:
    """The verb to record for a status change — terminal states get their own."""
    return {"shipped": "shipped", "dropped": "dropped"}.get(to_status, "status_changed")


def slice_activity(slice_):
    """Read-only, chronological activity for one slice — its own events plus its
    bites' events, oldest-first — so the detail reads like a comment thread."""
    from django.db.models import Q

    from tuckit.core.models import ActivityEvent, Bite

    bite_ids = list(Bite.objects.filter(slice=slice_).values_list("id", flat=True))
    # "id" as a secondary key so events sharing a created_at have a fixed,
    # reproducible order — export's collect() sorts to match this exactly.
    return list(
        ActivityEvent.objects.filter(org=slice_.org)
        .filter(Q(target_type="slice", target_id=slice_.id)
                | Q(target_type="bite", target_id__in=bite_ids))
        .order_by("created_at", "id")
    )


def parent_slice_ids(bite_ids) -> dict:
    """{bite_id: owning slice id} for the bites that still exist. A bite deleted
    by the very event being reported has no row left, so it is simply absent."""
    from tuckit.core.models import Bite

    if not bite_ids:
        return {}
    return dict(
        Bite.objects.filter(id__in=bite_ids).values_list("id", "slice_id")
    )


def active_targets(org, window_seconds: int = 300) -> dict:
    """{slice_id: (last_touch, verb, label)} for slices an agent touched inside
    the window — "who is holding what, right now".

    Derived on read and never stored, for the same reason as slice_stage(): a
    column would need rewriting on every bite transition and would be wrong the
    first time anything wrote around it.

    Bite events fold onto their parent slice. A bite has no element of its own
    on a live screen — it surfaces as its slice's progress — so its activity
    belongs to the card the viewer can actually see.

    Agent-only on purpose: warmth answers "an agent is working here", and a
    human's own edits lighting up their own board would be noise.
    """
    from datetime import timedelta

    from django.utils import timezone

    since = timezone.now() - timedelta(seconds=window_seconds)
    rows = list(
        ActivityEvent.objects.filter(
            org=org, source="agent", created_at__gte=since,
            target_type__in=("slice", "bite"),
        )
        .order_by("id")  # ascending: last write per slice wins below
        .values_list("target_type", "target_id", "verb", "target_label", "created_at")
    )
    if not rows:
        return {}
    owning = parent_slice_ids([tid for ttype, tid, *_ in rows if ttype == "bite"])
    active = {}
    for target_type, target_id, verb, label, created_at in rows:
        slice_id = target_id if target_type == "slice" else owning.get(target_id)
        if slice_id is None:
            continue  # bite deleted by this very event — nothing to attribute it to
        active[slice_id] = (created_at, verb, label)
    return active


def latest_activity_id(org) -> int:
    """The org's activity cursor: max ActivityEvent id, or 0 when there are none.
    Monotonic, so a change anywhere in the org strictly increases it."""
    from django.db.models import Max
    return ActivityEvent.objects.filter(org=org).aggregate(m=Max("id"))["m"] or 0


def events_since(org, since: int) -> list:
    """Events newer than the `since` cursor, oldest-first, scoped to the org."""
    return list(
        ActivityEvent.objects.filter(org=org, id__gt=since).order_by("id")
    )
