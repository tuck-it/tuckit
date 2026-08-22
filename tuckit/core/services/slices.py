from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from tuckit.core.entitlements import assert_can_write
from tuckit.core.models import Area, Org, Slice
from tuckit.core.services.activity import record_activity, status_verb
from tuckit.core.services.bites import bite_progress
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.ranking_helpers import rank_for
from tuckit.core.services.tags import get_or_create_tags
from tuckit.core.services.validation import validate_choice
from tuckit.core.services.watches import answer_watches, close_watches


def list_slices(area: Area, status: str | None = None, tag: str | None = None) -> QuerySet:
    # select_related("org") so {% ref_of %} on every row doesn't fire its own
    # SELECT against core_org — this feeds the area board's flat-list views.
    qs = Slice.objects.filter(area=area).select_related("org")
    if status:
        qs = qs.filter(status=status)
    if tag:
        qs = qs.filter(tags__name=tag)
    return qs


def query_slices(org, *, area=None, status=None, tag=None, query=None,
                 assignee_member=None, include_inbox=False, inbox_only=False,
                 limit=None) -> list[Slice]:
    """Org-wide slice query used by the MCP list_slices tool. All filters optional;
    with no `area` it searches the whole org. `query` = icontains on title/spec.

    Inbox slices (area IS NULL) are excluded by default — the board and this
    query are not where the Inbox is read from; use inbox_slices() for that, or
    pass include_inbox=True to opt back in. Asking for a specific `area`
    implies you already know inbox items can't match, so the exclusion is
    skipped rather than filtering twice.

    `inbox_only=True` inverts the split: the Inbox and nothing else, via the
    shared inbox_filter() predicate, with tag/query/assignee still applied on
    top. It is the searchable form of the same set inbox_slices() gives the
    Inbox screen — the two differ only in ordering and select_related, never in
    membership.

    Because inbox_filter() pins status='open', combining `inbox_only` with a
    `status` of anything else returns nothing: a capture that was shipped or
    dropped has LEFT the Inbox, so asking for a dropped Inbox item is asking
    for a contradiction. Those slices are still reachable — drop `inbox_only`
    and filter by status, which searches the whole org including unfiled work.
    """
    # Annotated here so list_slices can report each row's stage without two
    # queries per row. Must precede the .distinct() and the slice below —
    # annotating an already-sliced queryset raises.
    qs = annotate_stage_counts(
        Slice.objects.filter(org=org).select_related("area", "assignee__user", "org")
    )
    if inbox_only:
        qs = inbox_filter(qs)
    elif not include_inbox and area is None:
        qs = filed_slices(qs)
    if area is not None:
        qs = qs.filter(area=area)
    if status:
        qs = qs.filter(status=status)
    if tag:
        qs = qs.filter(tags__name=tag)
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(spec__icontains=query))
    if assignee_member is not None:
        qs = qs.filter(assignee=assignee_member)
    # order_by is explicit because the stage annotation adds a GROUP BY, and
    # Django does not apply Meta.ordering to aggregate queries — without this the
    # rank order silently disappears and the board comes back in table order.
    qs = qs.prefetch_related("tags").distinct().order_by("rank")
    if limit:
        qs = qs[:limit]
    return list(qs)


STATUS_ORDER = ["open", "shipped", "dropped"]


def grouped_slices(area: Area) -> list[tuple[str, list[Slice]]]:
    """Slices of an area grouped by status in canonical order:
    list of (status, [slices]) tuples. Tags are prefetched."""
    slices = list(list_slices(area).prefetch_related("tags"))
    return [(s, [x for x in slices if x.status == s]) for s in STATUS_ORDER]


def allocate_number(org: Org) -> int:
    """Atomically mint the next per-org number (shared by Slices and Tickets)."""
    locked = Org.objects.select_for_update().get(pk=org.pk)
    number = locked.next_slice_number
    locked.next_slice_number = number + 1
    locked.save(update_fields=["next_slice_number"])
    return number


def create_slice(
    org: Org,
    *,
    area: Area | None = None,
    title: str,
    spec: str = "",
    constraints: str = "",
    status: str = "open",
    tags: list[str] | None = None,
    before: Slice | None = None,
    after: Slice | None = None,
    source: str = "human",
    assignee_member=None,
    external_key: str = "",
    number: int | None = None,
    created_by=None,
    member=None,
) -> Slice:
    """Create a slice. `area` is optional — omit it (or pass None) and the
    slice lands in the Inbox, picked up by inbox_slices(). `org` is the first
    argument because a slice may have no area, so org can no longer be
    derived by dereferencing area.org.

    `created_by` is the OrgMember who captured it (None for an agent with no
    resolvable member) — the "Captured by" line on the detail panel and the
    Inbox row read it, falling back to `source`.

    An `external_key` that already exists updates that slice in place instead
    of duplicating, carrying through title/spec/constraints/tags/assignee, and
    filing it if `area` is given."""
    assert_can_write(org)
    if area is not None and area.org_id != org.id:
        raise InvalidValue("area belongs to a different org")
    if external_key:
        existing = Slice.objects.filter(org=org, external_key=external_key).first()
        if existing is not None:
            # Idempotent: a re-run with the same key updates in place, no duplicate.
            # Status is deliberately NOT touched here — create defaults to 'open' and
            # would otherwise regress a slice that already progressed; use update_slice
            # to move status. Empty spec/constraints are treated as "unchanged"
            # (`or None`), so a re-run that omits them keeps what is there.
            #
            # `area` and `created_by` go through set_slice_area()/a direct write
            # rather than update_slice(), which takes neither. They used to be
            # dropped on the floor here: an agent re-running create_slice with
            # the same key and a new area_id got silence, while the docstring
            # promised "Setting an area later files it."
            update_slice(
                existing, title=title, spec=spec or None,
                constraints=constraints or None, tags=tags,
                assignee=(1 if assignee_member is not None else None),
                assignee_member=assignee_member, source=source, member=member,
            )
            if area is not None and area.id != existing.area_id:
                set_slice_area(existing, area, source=source, member=member)
            if created_by is not None and existing.created_by_id is None:
                # Only fills a blank: the first capturer is a fact about the
                # capture, not something a later re-run reassigns.
                existing.created_by = created_by
                existing.save(update_fields=["created_by", "updated_at"])
            return existing
    validate_choice(status, Slice.STATUS_CHOICES, "status")
    rank = rank_for(Slice, {"area": area}, before=before, after=after)
    with transaction.atomic():
        if number is None:
            number = allocate_number(org)
        slice_ = Slice.objects.create(
            area=area,
            org=org,
            title=title,
            spec=spec,
            constraints=constraints,
            status=status,
            rank=rank,
            source=source,
            number=number,
            external_key=external_key,
            assignee=assignee_member,
            created_by=created_by,
            completed_at=timezone.now() if status == "shipped" else None,
        )
        if tags:
            slice_.tags.set(get_or_create_tags(org, tags))
        record_activity(org, source=source, verb="created", target=slice_, member=member)
    return slice_


def update_slice(
    slice_: Slice,
    *,
    title: str | None = None,
    spec: str | None = None,
    constraints: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    duplicate_of: Slice | None = None,
    assignee=None,
    assignee_member=None,
    before: Slice | None = None,
    after: Slice | None = None,
    source: str = "human",
    member=None,
) -> Slice:
    """Update a slice. `status` folds in the old set_slice_status; before/after fold
    in reorder. `assignee` is a presence flag (non-None means "set assignee") and
    `assignee_member` is the already-resolved OrgMember (or None to clear) — the
    caller resolves the email/'me' spec so this service stays request-context-free."""
    assert_can_write(slice_.org)
    old_status = slice_.status
    if title is not None:
        slice_.title = title
    close_open_watches = False
    if spec is not None:
        slice_.spec = spec
        if spec.strip():
            # The decision record STAYS. It answers a different question from
            # the spec -- how this was decided, not what it is -- so there are
            # never "two answers" for one of them to win. An earlier version
            # cleared it here and destroyed it permanently (TP-238).
            #
            # What a written spec still does is CLOSE the record: propose_nodes
            # and choose_option reject a slice that has one, and the watches go
            # for the same reason -- a click channel with no open question
            # answers nothing. Here rather than in the MCP tool because the
            # browser's inline spec edit comes through this same service, and
            # doing it in the tool would leave live channels behind for
            # everybody who writes their spec in the browser. Deferred until
            # the atomic block below so it shares the fate of the write it
            # belongs to -- otherwise a validate_choice failure or a save()
            # error below would still delete the watches.
            close_open_watches = True
    if constraints is not None:
        slice_.constraints = constraints
    if duplicate_of is not None:
        slice_.duplicate_of = duplicate_of
    if status is not None:
        validate_choice(status, Slice.STATUS_CHOICES, "status")
        _apply_status(slice_, status)
    if assignee is not None:
        slice_.assignee = assignee_member
    if before is not None or after is not None:
        slice_.rank = rank_for(Slice, {"area": slice_.area}, before=before, after=after)
    with transaction.atomic():
        slice_.save()
        if close_open_watches:
            close_watches(slice_)
        if tags is not None:
            slice_.tags.set(get_or_create_tags(slice_.org, tags))
        if status is not None and status != old_status:
            record_activity(
                slice_.org, source=source, verb=status_verb(status), member=member,
                target=slice_, from_value=old_status, to_value=status,
            )
    return slice_


def _apply_status(slice_: Slice, status: str) -> None:
    slice_.status = status
    if status == "shipped":
        slice_.completed_at = slice_.completed_at or timezone.now()
    else:
        slice_.completed_at = None


# NOTE: a Slice's status is deliberately NOT mirrored back onto its originating
# Ticket. The Ticket's lifecycle ends at promotion; "is it delivered yet" is read
# from the Slice (`ticket.slice.status`). Copying it would drift the moment a
# shipped slice is reopened — which is exactly what the old _autoclose_ticket did.


def set_slice_status(slice_: Slice, status: str, *, source: str = "human", member=None) -> Slice:
    validate_choice(status, Slice.STATUS_CHOICES, "status")
    old_status = slice_.status
    _apply_status(slice_, status)
    with transaction.atomic():
        slice_.save(update_fields=["status", "completed_at", "updated_at"])
        if status != old_status:
            record_activity(
                slice_.org, source=source, verb=status_verb(status), member=member,
                target=slice_, from_value=old_status, to_value=status,
            )
    return slice_


def reorder_slice(slice_: Slice, *, before: Slice | None = None, after: Slice | None = None) -> Slice:
    slice_.rank = rank_for(Slice, {"area": slice_.area}, before=before, after=after)
    slice_.save(update_fields=["rank", "updated_at"])
    return slice_


def set_slice_area(slice_: Slice, area: Area | None, *, source: str = "human", member=None) -> Slice:
    """File a slice into `area`, or clear it (area=None) to send it back to the
    Inbox. Both directions are fully reversible — there is no one-way "promote"
    left; triage is just picking an area, and un-triage is un-picking one."""
    if area is not None and area.org_id != slice_.org_id:
        raise InvalidValue("cannot move a slice across orgs")
    old_area = slice_.area
    same = (area.id if area else None) == (old_area.id if old_area else None)
    slice_.area = area
    slice_.rank = rank_for(Slice, {"area": area})
    with transaction.atomic():
        slice_.save(update_fields=["area", "rank", "updated_at"])
        if not same:  # no spurious event when the area didn't change (e.g. concurrent resubmit)
            record_activity(
                slice_.org, source=source, verb="moved", target=slice_, member=member,
                from_value=old_area.name if old_area else "Inbox",
                to_value=area.name if area else "Inbox",
            )
    return slice_


def inbox_filter(qs: QuerySet) -> QuerySet:
    """The Inbox as a predicate: no area AND still open.

    The single definition of "is this in the Inbox", and the exact mirror of
    filed_slices(). Both halves of the split now read from one place:
    inbox_slices() is this plus the screen's ordering, and
    query_slices(inbox_only=True) is this plus the search filters.

    Status is part of the definition, not an extra filter one caller happens to
    apply. Dropping the `status="open"` half here would mean an agent that
    reads `inbox.open_count` from get_project_state() and then lists the Inbox
    to work through it gets two different sets the moment any unfiled capture
    was shipped or dropped — the second call silently contradicting the first,
    with nothing on either surface admitting they disagree.
    """
    return qs.filter(area__isnull=True, status="open")


def inbox_slices(org: Org) -> QuerySet:
    """Untriaged captures — the sole source for the Inbox screen. A slice with
    no area IS an inbox item; there is no separate model for it any more."""
    return (
        inbox_filter(Slice.objects.filter(org=org))
        # created_by__user: the row's "captured by" badge dereferences it, so
        # without this every row fires two more SELECTs.
        .select_related("org", "created_by__user")
        .order_by("-created_at")
    )


def filed_slices(qs: QuerySet) -> QuerySet:
    """Exclude Inbox items (area IS NULL) from a Slice queryset.

    The single definition of "is this filed" on the queryset side, mirroring
    inbox_slices()'s predicate on the other side of the split. Every query that
    must not surface unfiled captures — the Board, the org-wide flat status
    list, Home's your_turn, and query_slices' own default — filters through
    this rather than re-spelling `area__isnull=False`. Grouping/sorting code
    downstream (e.g. `s.area.name`) depends on this: an Inbox slice has no
    area to group or sort by."""
    return qs.filter(area__isnull=False)


# Workflow order: what a slice needs next, from undesigned to done. Derived on
# read and never stored — a column would need updating on every spec edit and
# bite transition, and would be wrong the first time anything wrote around it.
SLICE_STAGES = (
    "needs_design", "needs_steps", "executing", "ready_to_ship",
    "shipped", "dropped",
)

# Board columns for the stage pipeline. The board groups by derived stage, not
# stored status. dropped is not a column — the page surfaces it as a header
# count.
BOARD_STAGE_COLUMNS = ("needs_design", "needs_steps", "executing", "ready_to_ship", "shipped")


def stage_column(stage: str) -> str | None:
    """The board column a derived stage belongs to, or None if it is not a
    column (dropped). There is no folding left to do — derived stage and board
    column are 1:1."""
    return stage if stage in BOARD_STAGE_COLUMNS else None


def slice_stage(status: str, spec: str, bites_done: int, bites_total: int) -> str:
    """What to do next on this slice.

    Pure: every argument is a primitive, so the rules can be tested without a
    database. `bites_done`/`bites_total` must carry bite_progress() semantics —
    dropped bites excluded from both — or a slice whose last outstanding step
    was dropped never leaves 'executing'.

    The Plan layer is gone, so needs_plan/needs_bites collapse into a single
    needs_steps — the board has drawn them as one column since v0.35.0."""
    if status in ("shipped", "dropped"):
        # A finished slice has no next step. Deriving anyway would tell you to
        # brainstorm something already deployed.
        return status
    if not spec:
        return "needs_design"
    if bites_total == 0:
        return "needs_steps"
    if bites_done < bites_total:
        return "executing"
    return "ready_to_ship"


# What to tell an agent to do, per stage. One readable table rather than a
# branch ladder, and the only place this wording lives.
#
# Each sentence stands on its own, with the skill named in parentheses AFTER
# it. That ordering is deliberate: an agent carrying the tuckit plugin fires
# the named skill, and an agent without it still knows what to do rather than
# chasing a reference it cannot resolve. Naming the skill alone would serve
# only the first reader.
_STAGE_INSTRUCTION = {
    "needs_design": (
        "agree the design and write it into the spec before writing code. "
        "(skill: designing-a-slice)"
    ),
    "needs_steps": (
        "write the constraints and an ordered step checklist onto the slice "
        "before writing code. (skill: breaking-down-a-slice)"
    ),
    "executing": (
        "work the checklist, keeping each step's status current on the board. "
        "(skill: executing-a-slice)"
    ),
    "ready_to_ship": (
        "verify for real, land the branch, and record what happened on the "
        "slice. (skill: shipping-a-slice)"
    ),
}


def delegation_prompt(ref: str, title: str, stage: str) -> str | None:
    """The text a human copies to hand this slice to an agent.

    Pure, like slice_stage() above: every argument is a primitive, so the
    wording can be tested without a database.

    Returns None for a stage with no next step (shipped, dropped) — the caller
    renders no control at all. Not "", because the template must be able to
    tell "nothing to delegate" apart from a prompt that failed to build.

    The agent's SessionStart primer already establishes that tuckit is the
    source of truth and that state is read with get_project_state. This carries
    exactly the delta: WHICH slice, WHAT stage it is at, and WHICH skill that
    stage calls for.

    The stage name is emitted verbatim on purpose. The plugin skills' own
    descriptions key on the literal strings ("stage reads needs_steps", "stage
    reads executing", "stage reads ready_to_ship"), so naming the stage is the
    most reliable trigger available — prettifying it to "Needs steps" would
    weaken the mechanism this exists to pull.

    It points at the board rather than copying it: no spec, no constraints, no
    URL. Inlining the body would be re-briefing, which is the thing the board
    exists to delete, and a URL would invite scraping HTML over calling
    get_slice.
    """
    instruction = _STAGE_INSTRUCTION.get(stage)
    if instruction is None:
        return None
    return (
        f"{ref} — {title}\n"
        f"\n"
        f'Read it first: get_slice("{ref}")\n'
        f"Stage is {stage} — {instruction}"
    )


def stage_counts(slice_) -> tuple[int, int]:
    """(bites_done, bites_total) for one slice — reuses bite_progress() so the
    dropped-bite exclusion is stated once on the Python side."""
    return bite_progress(slice_)


def annotate_stage_counts(qs):
    """The same two numbers, computed in the database, so a list of slices
    costs no extra queries.

    Bites hang directly off the Slice now, so the nested plans__bites join is
    gone. distinct=True stays on every Count regardless — other multi-valued
    joins (tags) can still be present on the same queryset, and without it
    they would fan the rows out and multiply the counts. The failure is
    silent — the numbers stay plausible."""
    return qs.annotate(
        _bites_total=Count("bites", distinct=True, filter=~Q(bites__status="dropped")),
        _bites_done=Count("bites", distinct=True, filter=Q(bites__status="done")),
    )


def stage_of(slice_) -> str:
    """Stage for one slice. Uses annotate_stage_counts() output when present so
    list callers pay nothing, and falls back to querying for a bare instance."""
    if hasattr(slice_, "_bites_total"):
        counts = (slice_._bites_done, slice_._bites_total)
    else:
        counts = stage_counts(slice_)
    return slice_stage(slice_.status, slice_.spec, *counts)


NODE_KINDS = {"question", "option", "note"}

# The keys a caller may set. `chosen` is deliberately absent -- it records a
# human's pick and is written by the choice channel, not by the agent that put
# the options up. `at` is absent because the server stamps it.
_NODE_KEYS = ("id", "parent", "kind", "title", "summary", "body", "media", "recommended")


def propose_nodes(slice_, nodes, *, source: str = "agent", member=None) -> list[dict]:
    """Append nodes to a slice's decision_tree canvas. Returns what was added.

    Append-only on purpose: a branch that was explored and lost is part of the
    record, so nothing here edits or removes an existing node. The whole batch
    is validated before any of it is stored -- a half-applied proposal would
    leave a canvas nobody authored.
    """
    assert_can_write(slice_.org)
    if (slice_.spec or "").strip():
        raise InvalidValue(
            "this slice already has a spec, so its canvas shows the spec's own "
            "structure -- propose only while the design is still being made"
        )

    existing = list((slice_.decision_tree or {}).get("nodes", []))
    known = {n.get("id") for n in existing}
    has_root = any(not n.get("parent") for n in existing)
    # One timestamp for the batch: these nodes were thought of together, and
    # the client's entrance stagger already orders them by position.
    arrived_at = int(timezone.now().timestamp() * 1000)

    fresh = []
    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise InvalidValue("every node needs a non-empty id")
        if node_id in known:
            raise InvalidValue(f"node id {node_id!r} is already on this canvas")

        kind = node.get("kind") or "note"
        if kind not in NODE_KINDS:
            raise InvalidValue(f"kind must be one of {sorted(NODE_KINDS)}, not {kind!r}")

        parent = node.get("parent") or None
        if parent is None:
            if has_root:
                raise InvalidValue(
                    f"the canvas already has a root; give {node_id!r} a parent"
                )
            has_root = True
        elif parent not in known:
            raise InvalidValue(
                f"parent {parent!r} is not on this canvas -- send it earlier in "
                f"this same call, or in an earlier one"
            )

        clean = {k: node[k] for k in _NODE_KEYS if k in node}
        clean.update(id=node_id, parent=parent, kind=kind, at=arrived_at)
        fresh.append(clean)
        known.add(node_id)

    slice_.decision_tree = {"nodes": existing + fresh}
    with transaction.atomic():
        slice_.save(update_fields=["decision_tree", "updated_at"])
        # live.js polls the org activity cursor, so this row is what makes the
        # canvas grow without a reload rather than being mere bookkeeping.
        record_activity(
            slice_.org, source=source, verb="proposed", target=slice_,
            to_value=str(len(fresh)), member=member,
        )
    return fresh


def choose_option(slice_, node_id: str, *, source: str = "human", member=None) -> dict:
    """Record a human's choice of an option that answers a question.

    The canvas is the thinking surface while the design is being made. Once a
    question is answered (by a human clicking an option in the browser), this
    function records that choice by setting `chosen` on the parent question node.

    The choice is only recorded while the design canvas is still open (spec is
    empty) — once the design is written, the canvas shows the spec's own
    structure instead.

    Returns the updated question node (the parent).
    """
    assert_can_write(slice_.org)
    if (slice_.spec or "").strip():
        raise InvalidValue(
            "this slice already has a spec, so its canvas shows the spec's own "
            "structure -- record a choice only while the design is still being made"
        )

    nodes = (slice_.decision_tree or {}).get("nodes", [])
    node_map = {n.get("id"): n for n in nodes}

    # Validate the option node exists.
    if node_id not in node_map:
        raise InvalidValue(f"node {node_id!r} is not on this canvas")

    node = node_map[node_id]

    # Validate the node is an option.
    if node.get("kind") != "option":
        raise InvalidValue(f"node {node_id!r} is not an option")

    # Validate the parent (question) exists.
    parent_id = node.get("parent")
    if parent_id not in node_map:
        raise InvalidValue(
            f"parent node {parent_id!r} is not on this canvas"
        )

    question_node = node_map[parent_id]

    # Validate the parent is a question.
    if question_node.get("kind") != "question":
        raise InvalidValue(
            f"parent node {parent_id!r} is not a question"
        )

    # Record the choice on the question node.
    question_node["chosen"] = node_id

    slice_.decision_tree = {"nodes": nodes}
    with transaction.atomic():
        slice_.save(update_fields=["decision_tree", "updated_at"])
        record_activity(
            slice_.org, source=source, verb="chose", target=slice_,
            to_value=(node.get("title") or node_id)[:50], member=member,
        )
        # Inside the transaction: an agent told an answer landed cannot be
        # un-told, so the message must not outlive a rolled-back write.
        # question_id=parent_id: only the watch(es) opened for THIS question
        # may be answered by this click -- a sibling question's watch, opened
        # separately, is a different capability channel.
        answer_watches(slice_, node_id, question_id=parent_id)
    return question_node
