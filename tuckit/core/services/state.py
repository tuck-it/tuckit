from datetime import timedelta

from django.utils import timezone

from tuckit.core.models import Area, Org, Slice, OrgStatSnapshot
from tuckit.core.services.activity import slice_activity
from tuckit.core.services.bites import list_bites, slice_bites
from tuckit.core.services.plans import list_plans
from tuckit.core.services.refs import ticket_ref
from tuckit.core.services.slices import (
    annotate_stage_counts, list_slices, stage_column, stage_of,
)
from tuckit.core.services.tickets import origin_ticket

_OPEN_BITE_STATUSES = ["todo", "doing"]
STALE_DAYS = 7


def _tag_names(slice_: Slice) -> list[str]:
    return [t.name for t in slice_.tags.all()]


def _slice_brief(slice_: Slice) -> dict:
    return {"id": slice_.id, "title": slice_.title, "tags": _tag_names(slice_)}


def _area_state(area: Area) -> dict:
    slices = list(list_slices(area).prefetch_related("tags"))
    shipped = [s for s in slices if s.status == "shipped"]
    someday = [s for s in slices if "someday" in _tag_names(s) and s.status != "shipped"]
    someday_ids = {s.id for s in someday}
    building = [s for s in slices if s.status == "building" and s.id not in someday_ids]
    planned = [s for s in slices if s.status == "planned" and s.id not in someday_ids]

    building_out = []
    open_bite_count = 0
    for s in building:
        open_bites = [b for b in slice_bites(s) if b.status in _OPEN_BITE_STATUSES]
        open_bite_count += len(open_bites)
        building_out.append(
            {
                "id": s.id,
                "title": s.title,
                "open_bites": [
                    {"id": b.id, "title": b.title, "status": b.status} for b in open_bites
                ],
            }
        )

    return {
        "name": area.name,
        "slug": area.slug,
        "shipped": [_slice_brief(s) for s in shipped],
        "building": building_out,
        "roadmap": [_slice_brief(s) for s in planned],
        "someday": [{"id": s.id, "title": s.title} for s in someday],
        "counts": {"open_bites": open_bite_count, "shipped": len(shipped)},
    }


def get_project_state(org: Org, area: Area | None = None, caller_user=None) -> dict:
    from tuckit.core.services.tickets import ticket_queryset
    areas = [area] if area is not None else list(Area.objects.filter(org=org, archived=False))
    inbox_qs = ticket_queryset(org)
    return {
        "caller": {
            "user_email": caller_user.email if caller_user is not None else None,
            "org_slug": org.slug,
            "org_name": org.name,
        },
        "org": {"name": org.name, "description": org.description},
        "inbox": {
            # One COUNT(*) + one 10-row fetch, not two full hydrations.
            "open_count": inbox_qs.count(),
            "recent": [{"id": t.id, "title": t.title} for t in inbox_qs[:10]],
        },
        "areas": [_area_state(a) for a in areas],
    }


def render_slice_markdown(slice_: Slice, with_activity: bool = False) -> str:
    tags = " ".join(f"#{t}" for t in _tag_names(slice_))
    lines = [f"# {slice_.title}", "", f"Status: {slice_.status}"]
    if tags:
        lines[-1] += f" · {tags}"
    # What to do next, derived from spec/plan/bite state — the first thing a
    # caller needs, and the reason get_slice is worth calling before anything
    # else. Never stored; see slice_stage().
    lines.append(f"Stage: {stage_of(slice_)}")
    # Where this work came from. The captured bodies live on the tickets, not
    # copied into spec, so this line is how an agent reaches the original text.
    linked = list(slice_.tickets.all())
    if linked:
        origin = origin_ticket(slice_)
        ordered = sorted(linked, key=lambda t: (t != origin, t.number or 0))
        lines.append("From: " + " · ".join(
            f"{ticket_ref(t)} (origin)" if t == origin else ticket_ref(t)
            for t in ordered
        ))
    lines.append("")
    if slice_.spec:
        lines += [slice_.spec, ""]
    for plan in list_plans(slice_):
        lines.append(f"## {plan.title or 'Plan'}")
        if plan.body:
            lines += [plan.body, ""]
        if plan.constraints:
            lines += ["### Constraints", plan.constraints, ""]
        for b in list_bites(plan):
            check = "x" if b.status == "done" else " "
            lines.append(f"- [{check}] {b.title}")
            if b.body:
                lines += [f"      {line}" for line in b.body.splitlines()]
        lines.append("")
    out = "\n".join(lines).rstrip() + "\n"
    if with_activity:
        out += _render_activity(slice_)
    return out


def render_ticket_markdown(ticket) -> str:
    """A ticket as markdown. For a promoted ticket the delivery status is read
    live off the slice rather than stored here, so this is the one place an
    agent needs to look to find out where a capture ended up."""
    lines = [f"# {ticket.title}", "", f"Status: {ticket.status}"]
    # Reverse OneToOne raises RelatedObjectDoesNotExist, which subclasses
    # AttributeError — so getattr's default covers the unpromoted case.
    promoted = getattr(ticket, "slice", None)
    if promoted is not None:
        from tuckit.core.services.refs import slice_ref
        lines[-1] += f" → slice {slice_ref(promoted)} ({promoted.status})"
    lines.append("")
    if ticket.body:
        lines += [ticket.body, ""]
    return "\n".join(lines).rstrip() + "\n"


def _render_activity(slice_: Slice) -> str:
    events = slice_activity(slice_)
    if not events:
        return ""
    rows = ["", "## Activity", ""]
    for e in events:
        when = e.created_at.date().isoformat()
        if e.verb == "noted":
            rows.append(f"- {when} · {e.actor} noted: {e.body}")
        elif e.from_value or e.to_value:
            rows.append(f"- {when} · {e.actor} {e.verb} ({e.from_value}→{e.to_value})")
        else:
            rows.append(f"- {when} · {e.actor} {e.verb}")
    return "\n".join(rows) + "\n"


def home_state(org: Org) -> dict:
    """Slice data for Home's `in progress` and `shipped` bands, plus the two
    backlog counts the footer link needs.

    No hidden filters. Every `building` slice is in `building` — including ones
    that also appear in your_turn() and ones tagged `someday`. The old version
    removed both, so a slice could read `building` everywhere else in the app
    and simply not be on Home.

    The backlog is returned as counts, not rows: listing planned work here would
    duplicate the Board, which is the surface for it.
    """
    slices = list(
        Slice.objects.filter(area__org=org)
        .select_related("area").prefetch_related("tags")
    )
    now = timezone.now()
    stale_cutoff = now - timedelta(days=STALE_DAYS)
    building = sorted(
        [s for s in slices if s.status == "building"],
        # False sorts before True, so stalled slices come first. Staleness is a
        # sort key here and nowhere a filter.
        key=lambda s: (s.updated_at >= stale_cutoff, s.area.name, s.rank),
    )
    shipped = sorted(
        [s for s in slices if s.status == "shipped"],
        key=lambda s: s.completed_at or s.updated_at, reverse=True,
    )
    week_ago = now - timedelta(days=7)
    return {
        "building": building,
        "shipped": shipped,
        "planned_ct": sum(1 for s in slices if s.status == "planned"),
        "someday_ct": sum(
            1 for s in slices
            if s.status != "shipped" and "someday" in _tag_names(s)
        ),
        "shipped_week_ct": sum(
            1 for s in shipped if s.completed_at and s.completed_at >= week_ago
        ),
    }


def snapshot_today(org: Org, state: dict, your_turn_ct: int) -> None:
    """Upsert today's count row for `org`.

    Nothing renders these numbers any more — the four stat cards that did were
    showing the same values as the lists directly below them. The write stays
    because the daily history is the one thing that cannot be reconstructed
    later; a future metrics screen will want it. Lazy (called on Home load), so
    no scheduler is needed.

    Org-scoped: OrgStatSnapshot is keyed by (org, date) via
    uniq_org_snapshot_per_day.
    """
    OrgStatSnapshot.objects.update_or_create(
        org=org,
        date=timezone.localdate(),
        defaults={
            "building_ct": len(state["building"]),
            "backlog_ct": state["planned_ct"] + state["someday_ct"],
            "shipped_week_ct": state["shipped_week_ct"],
            "attention_ct": your_turn_ct,
        },
    )


def your_turn(org: Org) -> list[dict]:
    """Work that cannot move without a human decision.

    Deliberately narrow:

    - `needs_plan` / `needs_bites` are excluded because an agent can do them —
      create_plan and add_bites exist for exactly that. Including them turns
      this band into a daily nag.
    - `planned` slices with an empty spec are excluded because promote never
      copies a ticket body, so every freshly promoted slice is specless.
      Including them would empty the whole backlog onto Home.
    - Open tickets collapse to ONE aggregate row. The Inbox is already a
      dedicated surface with its own badge; repeating twelve rows here is
      duplication, and a long list of things you haven't triaged reads as
      accusation rather than information.

    Staleness is not an inclusion rule — it is the sort key. A "stale" section
    is a guilt list: it only grows, and it can never be cleared.
    """
    from tuckit.core.services.slices import annotate_stage_counts, stage_of
    from tuckit.core.services.tickets import ticket_queryset

    now = timezone.now()
    # order_by is explicit: annotate_stage_counts adds a GROUP BY and Django
    # drops Meta.ordering from aggregate queries. sqlite hands back rowid order
    # anyway, so without this the sort looks fine locally and is undefined on
    # Postgres.
    qs = (
        annotate_stage_counts(
            Slice.objects.filter(area__org=org, status="building")
            .select_related("area")
        )
        .prefetch_related("tags")
        .order_by("updated_at")
    )
    _ACTIONS = {"needs_design": "write the spec", "ready_to_ship": "verify and ship"}
    items: list[dict] = []
    for s in qs:
        action = _ACTIONS.get(stage_of(s))
        if action is None:
            continue
        items.append({
            "slice": s,
            "action": action,
            "days": (now - s.updated_at).days,
            "since": s.updated_at,
        })
    items.sort(key=lambda it: it["since"])

    open_tickets = ticket_queryset(org).count()
    if open_tickets:
        items.append({
            "tickets": open_tickets,
            "action": f"{open_tickets} waiting for triage",
        })
    return items


def roadmap_state(org: Org) -> dict:
    """Non-dropped slices grouped by roadmap status — powers the Roadmap board
    and its distribution counts."""
    slices = list(
        Slice.objects.filter(area__org=org)
        .exclude(status="dropped")
        .select_related("area")
        .prefetch_related("tags")
    )

    def bucket(status: str) -> list:
        return sorted(
            [s for s in slices if s.status == status],
            key=lambda s: (s.area.name, s.rank),
        )

    shipped = sorted(
        [s for s in slices if s.status == "shipped"],
        key=lambda s: (s.completed_at or s.updated_at),
        reverse=True,
    )
    return {
        "planned": bucket("planned"),
        "building": bucket("building"),
        "shipped": shipped,
    }


ROADMAP_BOARD_ORDER = ["planned", "building", "shipped"]
ROADMAP_STATUS_KEYS = {"planned", "building", "shipped"}
STAGE_BOARD_ORDER = ["needs_design", "needs_plan", "executing", "ready_to_ship", "shipped"]


def cap_shipped(org: Org, shipped: list) -> tuple[list, int]:
    """Trim a recency-sorted shipped list to the org's board window.
    Returns (visible, total). Pure — operates on an already-fetched list."""
    total = len(shipped)
    if org.shipped_board_mode == "days":
        cutoff = timezone.now() - timedelta(days=org.shipped_board_limit)
        visible = [s for s in shipped if s.completed_at and s.completed_at >= cutoff]
    else:  # count
        visible = shipped[: org.shipped_board_limit]
    return visible, total


def roadmap_board_view(org: Org) -> dict:
    """Kanban groups keyed by derived stage (not stored status) + shipped
    overflow + dropped count, for the org Board tab.

    Each slice carries a `.stage` attribute so the card can badge needs_plan vs
    needs_bites and show the Ship button only on ready_to_ship."""
    # annotate_stage_counts adds a GROUP BY; Django then drops Meta.ordering, so
    # the explicit order_by is load-bearing (undefined order on Postgres without
    # it). area__name, rank matches roadmap_state's within-column order.
    qs = (
        annotate_stage_counts(
            Slice.objects.filter(area__org=org).select_related("area")
        )
        .prefetch_related("tags")
        .order_by("area__name", "rank")
    )
    columns: dict[str, list] = {key: [] for key in STAGE_BOARD_ORDER}
    dropped_count = 0
    shipped: list = []
    for s in qs:
        stage = stage_of(s)
        s.stage = stage
        if stage == "dropped":
            dropped_count += 1
            continue
        if stage == "shipped":
            shipped.append(s)
            continue
        columns[stage_column(stage)].append(s)

    # shipped column: recency-sorted then capped (cap_shipped count mode assumes
    # a recency-sorted list — see its docstring).
    shipped.sort(key=lambda s: (s.completed_at or s.updated_at), reverse=True)
    visible, total = cap_shipped(org, shipped)
    columns["shipped"] = visible
    return {
        "groups": [(key, columns[key]) for key in STAGE_BOARD_ORDER],
        "shipped_total": total,
        "shipped_hidden": total - len(visible),
        "dropped_count": dropped_count,
    }


AREA_BOARD_ORDER = ["planned", "building", "shipped"]
AREA_STATUS_KEYS = ROADMAP_STATUS_KEYS | {"dropped"}


def area_board_view(area: Area) -> dict:
    """Stage-keyed kanban groups + overflow/dropped meta for one Area's board —
    the area-scoped mirror of roadmap_board_view.

    `dropped` is deliberately absent from the columns and reported as a count;
    the page turns it into a ?status=dropped link. Every slice carries `.stage`.
    """
    from tuckit.core.services.tickets import ticket_queryset

    qs = (
        annotate_stage_counts(
            Slice.objects.filter(area=area).select_related("area")
        )
        .prefetch_related("tags")
        .order_by("rank")  # explicit: annotate_stage_counts drops Meta.ordering
    )
    columns: dict[str, list] = {key: [] for key in STAGE_BOARD_ORDER}
    dropped_count = 0
    shipped: list = []
    for s in qs:
        stage = stage_of(s)
        s.stage = stage
        if stage == "dropped":
            dropped_count += 1
            continue
        if stage == "shipped":
            shipped.append(s)
            continue
        columns[stage_column(stage)].append(s)

    shipped.sort(key=lambda s: (s.completed_at or s.updated_at), reverse=True)
    visible, total = cap_shipped(area.org, shipped)
    columns["shipped"] = visible

    active = any(columns[key] for key in STAGE_BOARD_ORDER if key != "shipped")
    return {
        "groups": [(key, columns[key]) for key in STAGE_BOARD_ORDER],
        "shipped_total": total,
        "shipped_hidden": total - len(visible),
        "dropped_count": dropped_count,
        # Untriaged tickets filed to this area. NOT a board column: a Ticket has
        # not been committed to, and putting it next to a stage column collapses
        # the very distinction the strip exists to show.
        "tickets": list(ticket_queryset(area.org, status="open", area=area)),
        # A capped-out or dropped slice still means "this area is not empty".
        "has_any_slice": active or total > 0 or dropped_count > 0,
    }


def recent_activity(org: Org, limit: int = 8) -> list:
    """The org's most recent activity events (newest first, capped)."""
    return list(org.activity.all()[:limit])


def since_last_visit(org: Org, member, limit: int = 10) -> dict:
    """Recent org activity, plus how much of it is news to this member.

    `is_new` is stamped on each event for the template (an instance attribute —
    nothing is written back). The count deliberately ignores `human` events: in
    a solo org every human event is the viewer's own, and badging your own work
    as news is noise. Human rows still render, for context.

    Read-only. The caller must invoke mark_home_seen() AFTER this — see there.
    """
    seen = getattr(member, "home_seen_at", None) if member is not None else None
    events = list(org.activity.all()[:limit])
    new_count = 0
    for e in events:
        e.is_new = bool(seen and e.created_at > seen)
        if e.is_new and e.actor == "agent":
            new_count += 1
    return {"events": events, "new_count": new_count}


def mark_home_seen(member) -> None:
    """Advance the member's Home watermark to now.

    Ordering is load-bearing: call this only AFTER since_last_visit() has
    computed what was new, or the band renders its own visit as already-seen
    and the badge is permanently zero.
    """
    if member is None:
        return
    member.home_seen_at = timezone.now()
    member.save(update_fields=["home_seen_at"])
