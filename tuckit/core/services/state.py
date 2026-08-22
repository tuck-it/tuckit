from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from tuckit.core.models import Area, Org, Slice, OrgStatSnapshot
from tuckit.core.services.activity import slice_activity
from tuckit.core.services.bites import list_bites
from tuckit.core.services.canvas import spine_for
from tuckit.core.services.slices import (
    PRIORITY_ORDER, annotate_stage_counts, filed_slices, inbox_slices, list_slices,
    priority_sort_key, stage_column, stage_of,
)

STALE_DAYS = 7


def _tag_names(slice_: Slice) -> list[str]:
    return [t.name for t in slice_.tags.all()]


def _slice_brief(slice_: Slice) -> dict:
    return {"id": slice_.id, "title": slice_.title, "tags": _tag_names(slice_)}


# How many open slices one area may spell out before the response starts
# summarising instead. get_project_state is the FIRST call of every session, and
# an uncapped roadmap made it grow without limit: at 140 open slices the reply
# was a multi-thousand-token wall, so the one tool built to orient you got less
# usable exactly as the board got harder to read. Whatever is cut is always
# reported -- a silent truncation reads as "that was all of it", which is a
# worse failure than the wall.
ROADMAP_LIMIT = 20


def _area_state(area: Area, *, limit: int = ROADMAP_LIMIT) -> dict:
    slices = list(list_slices(area).prefetch_related("tags"))
    shipped = [s for s in slices if s.status == "shipped"]
    open_ = [s for s in slices if s.status == "open"]
    dropped = [s for s in slices if s.status == "dropped"]

    # Sliced in Python, not in the query. The rows are already hydrated for the
    # counts below, so cutting here costs nothing and pushing the limit into SQL
    # would cost one COUNT per area per status -- an N+1 bought for no gain. The
    # payload is what was too big, never the fetch.
    #
    # Sorted BEFORE the cut. Without this the cap keeps whichever slices sat
    # highest in the manual order, which is an arbitrary sample dressed up as a
    # summary -- exactly what TP-253 shipped, and what this repays. list_slices
    # orders by priority already, but that is not something this line should
    # have to depend on: the sort is what makes the cut meaningful, so it is
    # stated where the cut happens.
    open_.sort(key=priority_sort_key)
    visible = open_[:limit]

    return {
        "name": area.name,
        "slug": area.slug,
        "shipped": [_slice_brief(s) for s in shipped],
        "roadmap": [_slice_brief(s) for s in visible],
        # open/dropped were both absent. Without `open` the caller had to count
        # the roadmap array by hand (and now cannot, since it is capped);
        # without `dropped` there was no way to learn what this board does with
        # what it captures.
        "counts": {
            "open": len(open_),
            "shipped": len(shipped),
            "dropped": len(dropped),
        },
        "roadmap_omitted": len(open_) - len(visible),
    }


def get_project_state(org: Org, area: Area | None = None, caller_user=None) -> dict:
    areas = [area] if area is not None else list(Area.objects.filter(org=org, archived=False))
    # The Inbox is area-less Slices now, not a separate Ticket table — same
    # aggregate, one model. inbox_slices() is the single definition of the
    # predicate (see slices.py); spelling `area__isnull=True` here again is how
    # the two halves of the split drift apart.
    inbox_qs = inbox_slices(org)
    # inbox_slices() orders by -created_at, so the last row is the oldest thing
    # nobody has filed. "34 waiting" is a number you can look past; "the oldest
    # has sat untouched for 40 days" is one that decides something.
    oldest = inbox_qs.last()
    now = timezone.now()
    return {
        "caller": {
            "user_email": caller_user.email if caller_user is not None else None,
            "org_slug": org.slug,
            "org_name": org.name,
        },
        "org": {
            "name": org.name,
            "description": org.description,
            # What counts as which priority, in this org's own words. Handed to
            # the agent because the agent is what classifies; no other tracker
            # gives its classifier this, which is why "when is it urgent?" lives
            # in everyone's prompts instead of on their board.
            "priority_policy": org.priority_policy,
        },
        "totals": _org_totals(org),
        "inbox": {
            # One COUNT(*) + one 10-row fetch, not two full hydrations.
            "open_count": inbox_qs.count(),
            "oldest_idle_days": (now - oldest.updated_at).days if oldest else None,
            "recent": [{"id": t.id, "title": t.title} for t in inbox_qs[:10]],
        },
        "areas": [_area_state(a) for a in areas],
    }


def _org_totals(org: Org) -> dict:
    """The shape of the pile, as opposed to its contents.

    `drop_ratio` is the number this board could never show: the share of
    everything ever captured that a human later decided was not work. It is the
    denominator for "will anyone actually do this later?" -- a question the
    review skills ask on every finding and, without this, answer from nothing.

    `by_source` is free for the same reason: create_slice stamps source="agent"
    on every MCP write, so who fills this board has been recorded all along and
    read by no one.

    Two GROUP BY queries for the whole org, not one per area.
    """
    rows = org.slices.values("status").annotate(n=Count("id"))
    counts = {r["status"]: r["n"] for r in rows}
    open_ct = counts.get("open", 0)
    shipped_ct = counts.get("shipped", 0)
    dropped_ct = counts.get("dropped", 0)
    decided = open_ct + shipped_ct + dropped_ct

    by_source = {
        r["source"]: r["n"]
        for r in org.slices.values("source").annotate(n=Count("id"))
    }
    return {
        "open": open_ct,
        "shipped": shipped_ct,
        "dropped": dropped_ct,
        "drop_ratio": round(dropped_ct / decided, 2) if decided else 0.0,
        "by_source": {
            "human": by_source.get("human", 0),
            "agent": by_source.get("agent", 0),
        },
    }


def _node_list(nodes):
    return " \u00b7 ".join(
        f"[{n['id']}] {n.get('title', '')}"
        + (" (recommended)" if n.get("recommended") else "")
        for n in nodes)


def _render_decisions(slice_):
    """The decision record, in reading order, with every node id spelled out.

    The ids are why this exists. propose() rejects a node whose parent is not
    the option that won, and a session that cannot see which option won can
    only ever fail that check -- which is the likeliest reason the convention
    drifted for as long as it did.

    Bodies are deliberately left out. A 25-node canvas carries several
    thousand words of reasoning, and swamping every get_slice with it would
    buy nothing an agent needs: the ids and the states are what it acts on,
    and the prose is what the human reads on the board.
    """
    nodes = (slice_.decision_tree or {}).get("nodes", [])
    if not nodes:
        return []

    rows = ["## Decisions", ""]
    for row in spine_for(nodes, closed=bool((slice_.spec or "").strip())):
        node = row["node"]
        title = node.get("title", "")
        if row["row"] == "question":
            line = f"- [{node['id']}] {title} -- {row['state']}"
            if row["locked"]:
                line += ", locked"
            rows.append(line)
            if row["rejected"]:          # passed over: nothing won
                rows.append("  - not taken: " + _node_list(row["rejected"]))
            if row["options"]:
                rows.append("  - candidates: " + _node_list(row["options"]))
        elif row["row"] == "chosen":
            rows.append(f"  - chosen: [{node['id']}] {title}")
            # The losers ride on the winner's row, so the answer is printed
            # before the list of what it beat -- the same order as the screen.
            if row["rejected"]:
                rows.append("  - rejected: " + _node_list(row["rejected"]))
        else:
            rows.append(f"- [{node['id']}] {title} (note)")
    return rows + [""]


def render_slice_markdown(slice_: Slice, with_activity: bool = False, *,
                          bites=None, activity=None) -> str:
    tags = " ".join(f"#{t}" for t in _tag_names(slice_))
    lines = [f"# {slice_.title}", "", f"Status: {slice_.status}"]
    if tags:
        lines[-1] += f" · {tags}"
    # Only when someone set it. An unranked slice printing a number would be the
    # renderer inventing a decision nobody made -- the same rule the board badge
    # follows. What the number MEANS is org.priority_policy, which the agent
    # already has from get_project_state; repeating it on every slice would be
    # the same paragraph N times in one session.
    if slice_.priority:
        lines.append(f"Priority: {slice_.priority}")
    # What to do next, derived from the spec and the slice's steps — the first thing a
    # caller needs, and the reason get_slice is worth calling before anything
    # else. Never stored; see slice_stage().
    lines.append(f"Stage: {stage_of(slice_)}")
    lines.append("")
    if slice_.spec:
        lines += [slice_.spec, ""]
    # Constraints is a Slice field now (Task 10 gave it a first-class editor).
    # Rendering it here is the whole point of promoting it: a human writes the
    # minefield map once and every later agent session reads it back through
    # get_slice. Left out, the field would be invisible to exactly the reader
    # it exists for.
    if slice_.constraints:
        lines += ["## Constraints", "", slice_.constraints, ""]
    # The design canvas, readable back at last. Until this landed an agent
    # could write the record but never read it, so it could not know which
    # option won -- and therefore could not hang its next node off it.
    lines += _render_decisions(slice_)
    # ONE flat checklist of every bite on the slice. The old renderer grouped
    # steps under Plan headings and then appended plan-less ones separately;
    # with the Plan layer gone that split has no meaning, and keeping the
    # `plan__isnull=True` filter would have hidden every bite migration 0045
    # reparented (it sets Bite.slice but leaves Bite.plan populated) — i.e.
    # every step that existed before this release.
    # Callers that already hold the slice's bites pass them in. The export
    # renders every slice in an org, and querying per slice here would make
    # that artifact N+1. Omitting the argument keeps the original behaviour,
    # so MCP get_slice is untouched.
    bites = list(list_bites(slice_)) if bites is None else list(bites)
    if bites:
        lines.append("## Steps")
        for b in bites:
            check = "x" if b.status == "done" else " "
            lines.append(f"- [{check}] {b.title}")
            if b.body:
                lines += [f"      {line}" for line in b.body.splitlines()]
        lines.append("")
    out = "\n".join(lines).rstrip() + "\n"
    if with_activity:
        out += _render_activity(slice_, activity=activity)
    return out


def _render_activity(slice_: Slice, activity=None) -> str:
    events = slice_activity(slice_) if activity is None else list(activity)
    if not events:
        return ""
    rows = ["", "## Activity", ""]
    for e in events:
        when = e.created_at.date().isoformat()
        if e.verb == "noted":
            rows.append(f"- {when} · {e.source} noted: {e.body}")
        elif e.from_value or e.to_value:
            rows.append(f"- {when} · {e.source} {e.verb} ({e.from_value}→{e.to_value})")
        else:
            rows.append(f"- {when} · {e.source} {e.verb}")
    return "\n".join(rows) + "\n"


def home_state(org: Org) -> dict:
    """Slice data for Home's `in progress` and `shipped` bands, plus the open
    count the footer link needs.

    `in_progress` is DERIVED (stage == 'executing'), not a stored flag. The old
    version filtered `status == "building"`, a switch a human had to flip by
    hand — nobody ever did, so the band was permanently empty while work was
    visibly happening. Deriving it means Home and the Board can never disagree.
    """
    from tuckit.core.services.slices import annotate_stage_counts, filed_slices, stage_of

    # order_by는 명시적이다 — annotate_stage_counts가 GROUP BY를 붙여 Django가
    # Meta.ordering을 버린다. sqlite는 rowid 순으로 돌려줘 로컬에선 멀쩡해 보이고
    # Postgres에서만 깨진다.
    #
    # filed_slices()로 거른다: in_progress의 정렬 키가 s.area.name을 참조한다.
    # slice_stage()는 area를 보지 않으므로 spec과 진행 중 bite가 있는 Inbox
    # 슬라이스는 정당하게 stage == "executing"에 도달하고, 그 순간 area가
    # None이라 AttributeError로 Home이 500난다. Inbox는 자기 화면이 있으니
    # Board와 동일하게 여기서도 제외한다.
    slices = list(
        annotate_stage_counts(
            filed_slices(Slice.objects.filter(org=org)).select_related("area", "org")
        )
        .prefetch_related("tags")
        .order_by(*PRIORITY_ORDER)
    )
    now = timezone.now()
    stale_cutoff = now - timedelta(days=STALE_DAYS)
    in_progress = sorted(
        [s for s in slices if stage_of(s) == "executing"],
        # False sorts before True, so stalled slices come first. Staleness is a
        # sort key here and nowhere a filter.
        #
        # This Python sort REPLACES the queryset's PRIORITY_ORDER for this band,
        # so priority has to be named again or it is silently dropped -- staleness
        # and area stay ahead of it (they group the band), priority orders within.
        key=lambda s: (s.updated_at >= stale_cutoff, s.area.name, *priority_sort_key(s)),
    )
    shipped = sorted(
        [s for s in slices if s.status == "shipped"],
        key=lambda s: s.completed_at or s.updated_at, reverse=True,
    )
    week_ago = now - timedelta(days=7)
    return {
        "in_progress": in_progress,
        "shipped": shipped,
        "open_ct": sum(1 for s in slices if s.status == "open"),
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
            "building_ct": len(state["in_progress"]),
            "backlog_ct": state["open_ct"],
            "shipped_week_ct": state["shipped_week_ct"],
            "attention_ct": your_turn_ct,
        },
    )


def your_turn(org: Org) -> list[dict]:
    """Work that cannot move without a human decision.

    Deliberately narrow:

    - `needs_steps` is excluded because an agent can do it — add_bites exists
      for exactly that. Including it turns this band into a daily nag.
    - `open` 슬라이스 중 stage가 needs_design / ready_to_ship인 것만 든다.
      needs_steps는 에이전트가 할 수 있어서 빠진다(add_bites가 그걸 위해
      있다) — 넣으면 이 밴드가 매일의 잔소리가 된다.
      예전에는 status='building'으로 한 번 더 걸렀는데, 그 스위치를 아무도 켜지
      않아 밴드가 통째로 비어 있었다. 실측(2026-07-27) needs_design은 4건이라
      백로그가 쏟아지지 않는다. 길어지면 그때 상한을 건다.
    - Unfiled Inbox captures collapse to ONE aggregate row. The Inbox is
      already a dedicated surface with its own badge; repeating twelve rows
      here is duplication, and a long list of things you haven't triaged
      reads as accusation rather than information.

    Staleness is not an inclusion rule — it is the sort key. A "stale" section
    is a guilt list: it only grows, and it can never be cleared.

    Inbox slices (area IS NULL) are excluded via filed_slices(): an unfiled
    capture is not yet work anyone has committed to, so "write the spec" is
    the wrong ask — triaging it (giving it an area) is the actual next step,
    and that lives on the Inbox screen, not here.
    """
    from tuckit.core.services.slices import annotate_stage_counts, filed_slices, inbox_slices, stage_of

    now = timezone.now()
    # order_by is explicit: annotate_stage_counts adds a GROUP BY and Django
    # drops Meta.ordering from aggregate queries. sqlite hands back rowid order
    # anyway, so without this the sort looks fine locally and is undefined on
    # Postgres.
    qs = (
        annotate_stage_counts(
            filed_slices(Slice.objects.filter(org=org, status="open"))
            .select_related("area", "org")
        )
        .prefetch_related("tags")
        # Deliberately NOT PRIORITY_ORDER. This band answers "what has been
        # waiting longest for a human", and sorting it by priority would bury a
        # stalled low-priority slice forever -- which is the state that most
        # needs a person to look. The next reader will think this was missed;
        # it was not.
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

    inbox_count = inbox_slices(org).count()
    if inbox_count:
        items.append({
            "inbox": inbox_count,
            "action": f"{inbox_count} in Inbox",
        })
    return items


def roadmap_state(org: Org) -> dict:
    """Non-dropped slices grouped by roadmap status — powers the Roadmap board
    and its distribution counts.

    Inbox slices (area IS NULL) are excluded via filed_slices(): bucket() below
    sorts by `s.area.name`, which is exactly the AttributeError an unfiled
    capture would trip, and even where it wouldn't crash the Inbox has its own
    screen — it does not belong on the org-wide flat status list."""
    slices = list(
        filed_slices(Slice.objects.filter(org=org))
        .exclude(status="dropped")
        .select_related("area", "org")
        .prefetch_related("tags")
    )

    def bucket(status: str) -> list:
        return sorted(
            [s for s in slices if s.status == status],
            key=lambda s: (s.area.name, *priority_sort_key(s)),
        )

    shipped = sorted(
        [s for s in slices if s.status == "shipped"],
        key=lambda s: (s.completed_at or s.updated_at),
        reverse=True,
    )
    return {
        "open": bucket("open"),
        "shipped": shipped,
    }


ROADMAP_BOARD_ORDER = ["open", "shipped"]
ROADMAP_STATUS_KEYS = {"open", "shipped"}
STAGE_BOARD_ORDER = ["needs_design", "needs_steps", "executing", "ready_to_ship", "shipped"]


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

    Each slice carries a `.stage` attribute so the card can badge needs_steps
    and show the Ship button only on ready_to_ship. Inbox slices (area IS
    NULL) are excluded via filed_slices() — the Board groups by area__name and
    an unfiled capture has none; it belongs on the Inbox screen, not here."""
    # annotate_stage_counts adds a GROUP BY; Django then drops Meta.ordering, so
    # the explicit order_by is load-bearing (undefined order on Postgres without
    # it). area__name, rank matches roadmap_state's within-column order.
    qs = (
        annotate_stage_counts(
            filed_slices(Slice.objects.filter(org=org)).select_related("area", "org")
        )
        .prefetch_related("tags")
        .order_by("area__name", *PRIORITY_ORDER)
    )
    columns: dict[str, list] = {key: [] for key in STAGE_BOARD_ORDER if key != "shipped"}
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


AREA_BOARD_ORDER = ["open", "shipped"]
AREA_STATUS_KEYS = ROADMAP_STATUS_KEYS | {"dropped"}


def area_board_view(area: Area) -> dict:
    """Stage-keyed kanban groups + overflow/dropped meta for one Area's board —
    the area-scoped mirror of roadmap_board_view.

    `dropped` is deliberately absent from the columns and reported as a count;
    the page turns it into a ?status=dropped link. Every slice carries `.stage`.

    No `filed_slices()` filter is needed here: scoping to one `area` already
    excludes Inbox slices (area IS NULL cannot match area=area).
    """
    qs = (
        annotate_stage_counts(
            Slice.objects.filter(area=area).select_related("area", "org")
        )
        .prefetch_related("tags")
        .order_by(*PRIORITY_ORDER)  # explicit: annotate_stage_counts drops Meta.ordering
    )
    columns: dict[str, list] = {key: [] for key in STAGE_BOARD_ORDER if key != "shipped"}
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
        if e.is_new and e.source == "agent":
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
