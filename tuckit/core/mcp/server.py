import os

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.transport_security import TransportSecuritySettings

from tuckit.core.mcp.auth import require_caller, require_org
from tuckit.core.models import OrgMember
from tuckit.core.mcp.serializers import activity_event_dict, area_dict, bite_dict, slice_dict
from tuckit.core.services.activity import add_note as _add_note
from tuckit.core.services.areas import create_area as _create_area
from tuckit.core.services.areas import list_areas as _list_areas
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.bites import (
    add_bites as _add_bites,
    list_bites as _list_bites,
    update_bite as _update_bite,
)
from tuckit.core.services.orgs import append_priority_policy as _append_priority_policy
from tuckit.core.services.resolve import get_area
from tuckit.core.services.resolve import get_bite as _resolve_bite
from tuckit.core.services.resolve import get_slice as _resolve_slice
from tuckit.core.services.resolve import get_slice_flexible as _resolve_slice_flexible
from tuckit.core.services.members import resolve_member
from tuckit.core.services.slices import create_slice as _create_slice
from tuckit.core.services.slices import propose_nodes as _propose_nodes
from tuckit.core.services.slices import query_slices as _query_slices
from tuckit.core.services.slices import set_slice_area as _set_slice_area
from tuckit.core.services.slices import stage_of
from tuckit.core.services.slices import update_slice as _update_slice
from tuckit.core.services.state import get_project_state as _get_project_state
from tuckit.core.services.state import render_slice_markdown
from tuckit.core.services.watches import open_watch as _open_watch

# `area_id` is `int | str | None` on every tool that can move or filter by area.
# There is no way to say "clear this field" with a plain `int | None` — None
# already means "leave it alone" — and clearing an area is not an edge case
# here: it is how a slice goes back to the Inbox, the reverse of filing it.
# Empty string means "the Inbox / no area", matching the `assignee=''` clears
# convention the same tools already use.


def _area_arg(org, area_id):
    """Resolve an `area_id` argument to (touched, area).

    `None` -> (False, None): omitted, leave whatever is there.
    `''`   -> (True, None):  the Inbox, i.e. no area.
    an id  -> (True, Area)."""
    if area_id is None:
        return False, None
    if isinstance(area_id, str):
        text = area_id.strip()
        if text == "":
            return True, None
        if not text.isdigit():
            # An area NAME, most likely. Say so instead of raising ValueError
            # out of int(), which reaches the caller as an opaque 500.
            raise InvalidValue(
                f"area_id must be an area id or '' for the Inbox, not {area_id!r} "
                f"— call list_areas to get the id"
            )
        area_id = int(text)
    return True, get_area(org, area_id)


def _acting_member(org, user):
    """The OrgMember behind an MCP call, or None when there is nobody to name.

    An OAuth token carries the human who authorized it, so an agent writing on
    someone's behalf records THAT person alongside source="agent" — the two are
    different questions ("which channel" vs "who"). A legacy ApiToken has no
    user at all and legitimately resolves to None; that is the nullable path,
    not an error, and those rows stay unattributed.
    """
    if user is None:
        return None
    return OrgMember.objects.filter(org=org, user=user).first()


# FastMCP's Streamable HTTP transport enables DNS-rebinding protection (Host/Origin
# header allowlisting) by default whenever `host` is unset/loopback (see
# mcp.server.fastmcp.server.FastMCP.__init__, which auto-builds a
# TransportSecuritySettings only for host in {"127.0.0.1", "localhost", "::1"}).
# That default allowlist only covers those three loopback host *values* with any
# port, which rejects legitimate requests carrying any other Host header (e.g. a
# reverse proxy's hostname, or Starlette TestClient's synthetic "testserver" Host)
# with a 421 Misdirected Request -- a real production footgun, not just a test
# inconvenience. We set the allowlist explicitly so it's visible and includes the
# hosts we actually expect: local dev (with and without the default :8000 port)
# plus Starlette's TestClient host used by our own test suite.
#
# Any deployment behind a reverse proxy / real hostname (e.g. the hosted app, or a
# self-hosted install) must add its public Host to the allowlist, otherwise every
# authenticated /mcp request 421s "Invalid Host header". Rather than hardcode a
# deployment-specific hostname here (this is the neutral public core), we read a
# comma-separated TUCKIT_MCP_ALLOWED_HOSTS env var and append it. Each host also
# gets an https:// origin entry (browser clients send Origin; server MCP clients
# usually don't, and absent Origin is already allowed). Empty/unset => local only.
_extra_hosts = [h.strip() for h in os.environ.get("TUCKIT_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
_extra_origins = [f"https://{h}" for h in _extra_hosts]

_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "localhost", "localhost:8000",
        "127.0.0.1", "127.0.0.1:8000",
        "testserver",  # Starlette TestClient, used by tests/test_mcp_e2e.py and test_mcp_auth.py
        *_extra_hosts,
    ],
    allowed_origins=[
        "http://localhost", "http://localhost:8000",
        "http://127.0.0.1", "http://127.0.0.1:8000",
        "http://testserver",
        *_extra_origins,
    ],
)

# The transport is configured where the ASGI app is built
# (tuckit/core/mcp/compose.py); the server object itself only carries the tools.
# See that module for why this runs stateless.
mcp = MCPServer("tuck-it")


@mcp.tool()
async def get_project_state(ctx: Context, area_id: int | None = None) -> dict:
    """Current project state (shipped/roadmap) plus the caller's identity
    (user_email, org). Optionally scope to one area by id.

    `inbox` counts the slices that have no area yet — things someone decided
    mattered before deciding where they belong. They are real slices, not a
    separate kind of object: give one an area (update_slice) and it joins that
    area's roadmap; clear the area and it comes back. `oldest_idle_days` is how
    long the oldest unfiled capture has sat untouched.

    `totals` is the shape of the board rather than its contents: open / shipped
    / dropped for the whole org, `drop_ratio` (the share of everything ever
    captured that someone later decided was not work), and `by_source`
    (human vs agent). Read `drop_ratio` before you file anything: it is the
    denominator for "will anyone actually do this later?", and a board that
    drops most of what it collects is telling you the honest answer is no.

    Each area's `roadmap` is capped, and what survives the cap is now the
    highest-priority work rather than whatever sat highest in the manual order.
    `counts.open` is the real number and `roadmap_omitted` is how many were
    left out — the list is a sample once that is above zero, never the whole
    board.

    `org.priority_policy` is what counts as which priority HERE, written by a
    person in their own words. Read it before you set a priority: 1 is the most
    urgent, 5 the least, and what qualifies for each is whatever that text says
    — not your own sense of what is usually urgent. An empty policy is normal;
    classify from general judgement then, and say that you did, so the person
    can correct you. Those corrections are how the policy gets written."""
    org, user = await require_caller(ctx)

    def _run():
        area = get_area(org, area_id) if area_id is not None else None
        return _get_project_state(org, area=area, caller_user=user)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def append_priority_policy(ctx: Context, line: str) -> dict:
    """Add one line to this org's priority policy — what counts as which
    priority, in this org's own words.

    Append only. You cannot edit or remove a line from here; a person does that
    in the web UI. That asymmetry is deliberate: the policy is written slowly,
    out of corrections to classifications that were wrong, and it is not
    something one call of yours should be able to undo.

    Do not call this on your own initiative. It is for a line your human partner
    has just agreed to — usually the reason they gave when they corrected a
    priority you set. Propose the wording, get a yes, then write it."""
    org, _user = await require_caller(ctx)

    def _run():
        return {"priority_policy": _append_priority_policy(org, line).priority_policy}

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_areas(ctx: Context) -> list[dict]:
    """List the org's areas, with the id of each.

    Call this first whenever you are about to file something. Areas are the
    only destination a slice can be filed into, and their ids are what
    `create_slice`/`update_slice` take — an agent that guesses instead of
    looking either fails or invents a duplicate area."""
    org = await require_org(ctx)

    def _run():
        return [area_dict(a) for a in _list_areas(org)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_area(ctx: Context, name: str, description: str = "") -> dict:
    """Create an area — a long-lived domain of responsibility that slices get
    filed into (backend, frontend, docs, infra).

    Call `list_areas` first and use what is already there. An org has a handful
    of areas and keeps them for years; they are not labels, milestones, or a
    folder per feature. If the work you are filing plausibly belongs under an
    existing area, it does — file it there and let the slice's own title say
    what it is.

    Create one only when a genuinely new standing concern appears and nothing
    on the list covers it. A near-duplicate of an existing area is worse than
    leaving a slice in the Inbox: the Inbox is a visible queue someone will
    triage, while a junk area quietly splits one area's work in two and nobody
    notices for months."""
    org, user = await require_caller(ctx)

    def _run():
        return area_dict(_create_area(
            org, name, description=description, source="agent",
            member=_acting_member(org, user),
        ))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_slices(
    ctx: Context,
    area_id: int | str | None = None,
    status: str | None = None,
    tag: str | None = None,
    query: str | None = None,
    assignee: str | None = None,
    limit: int | None = 50,
) -> list[dict]:
    """List/search slices — the one unit of work. All filters optional.

    `area_id`: omit it to search the whole org, INCLUDING slices that have no
    area yet; pass an id to scope to one area; pass '' for the Inbox — the
    still-open captures nobody has filed. Do that before assuming the org has
    nothing waiting: unfiled work is the easiest to miss and usually the
    oldest, and this returns exactly the slices get_project_state() counted in
    `inbox.open_count`.

    Being in the Inbox means two things at once: no area AND still open. A
    capture that was shipped or dropped without ever being filed has left it,
    so `area_id=''` will not return one — omit `area_id` and pass `status`
    instead to go looking for those.

    query = text match on title/spec. assignee = 'me' or an email.

    Each row carries `stage` — what that slice needs next, derived from its own
    state: needs_design (spec is empty — brainstorm and write the design doc into
    it), needs_steps (spec is written but it has no bites yet), executing,
    ready_to_ship, or shipped/dropped for finished work. Read progress from
    `stage`; `status` only ever records a decision (open/shipped/dropped).

    Every row also carries `age_days` (since it was created) and `idle_days`
    (since anything last changed on it). Read them before you add: an Inbox
    whose oldest capture is forty days untouched is telling you that one more
    capture is not what it needs."""
    org, user = await require_caller(ctx)

    def _run():
        touched, area = _area_arg(org, area_id)
        member = resolve_member(org, assignee, caller_user=user) if assignee else None
        rows = _query_slices(
            org, area=area, status=status, tag=tag, query=query,
            assignee_member=member, limit=limit,
            # An omitted area_id means "everything", not "everything already
            # filed": the service default hides area-less slices because the
            # Board cannot render them, and an agent inheriting that default
            # would be blind to the Inbox.
            include_inbox=not touched,
            inbox_only=touched and area is None,
        )
        # Merged here rather than inside slice_dict(): that serializer is shared
        # with create_slice/update_slice, which already know what they just
        # wrote.
        #
        # One `now` for the whole page. Letting each row read the clock makes a
        # single response measure its rows from different instants -- invisible
        # in a test, wrong in a long list.
        now = timezone.now()
        return [{**slice_dict(s, now=now), "stage": stage_of(s)} for s in rows]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def get_slice(ctx: Context, slice: int | str, with_activity: bool = False) -> str:
    """Return a slice rendered as markdown — everything known about one unit of
    work. `slice` may be a numeric id or a ref like 'ACM-42'. Set
    with_activity=true to append the activity/notes thread.

    Read this before touching the work. The sections are, in order: the spec
    (the design doc — what we are building and why), `## Constraints` (what you
    must not get wrong: landmines, invariants, the real definition of done —
    treat it as binding, it was written for exactly this moment), and
    `## Steps` (the bite checklist, with `[x]` for what is already done).
    `## Decisions` follows Constraints when the slice has a design canvas: the
    record in reading order, with each node's id, each question's state
    (answered / waiting / passed) and whether it is locked. Read it before
    calling `propose` -- the ids are what a new node's `parent` has to name.

    The `Stage:` line says what to do next: needs_design (spec is empty —
    brainstorm and write the design doc into it), needs_steps (spec is written
    but it has no bites yet), executing, ready_to_ship, or shipped/dropped.
    That line, not `Status:`, is where progress lives."""
    org = await require_org(ctx)

    def _run():
        s = _resolve_slice_flexible(org, slice)
        return render_slice_markdown(s, with_activity=with_activity)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def add_note(ctx: Context, slice: int | str, body: str) -> dict:
    """Append a note to a slice's activity thread. `slice` may be an id or a ref.

    A note is what HAPPENED — what you tried, what broke, what you decided and
    why, a PR link, why this is blocked. It is timestamped and append-only, so
    it is the right place for anything that is true of a moment rather than of
    the work.

    Choose between the three by asking who the reader is. `spec` is the design
    doc: what we are building and why, rewritten as understanding improves.
    `constraints` is the standing warning to whoever picks this up next —
    landmines and invariants that outlive any one session. A note is neither;
    it is the record of the session itself. Discovering a landmine is worth
    both: note that you hit it, and put the rule in `constraints` so the next
    agent never has to."""
    org, user = await require_caller(ctx)

    def _run():
        s = _resolve_slice_flexible(org, slice)
        return activity_event_dict(
            _add_note(s, body, source="agent", member=_acting_member(org, user))
        )

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_slice(
    ctx: Context,
    title: str,
    area_id: int | str | None = None,
    spec: str = "",
    constraints: str = "",
    status: str = "open",
    priority: int | None = None,
    tags: list[str] | None = None,
    assignee: str | None = None,
    external_key: str = "",
    after_id: int | None = None,
    before_id: int | None = None,
) -> dict:
    """Create a slice — the one unit of work in tuckit.

    A slice is a thing worth doing, from the moment someone thinks it matters
    through to the moment it ships. There is no lighter object to capture into
    and no heavier one to graduate to; this is the whole vocabulary.

    Leave `area_id` empty to park it in the Inbox (you know it matters, not yet
    where it belongs) — capturing without filing is a first-class path, not a
    fallback. Setting an area later files it, and clearing the area sends it
    back; both directions are reversible, so nothing here is a one-way door.

    `spec` is the design doc — what we are building and why. Leave it blank if
    the work has not been thought through: an empty spec is the signal that
    reads back as stage 'needs_design', and pre-filling it with a rough capture
    makes undesigned work look designed to the next agent.

    `constraints` is what a later agent must not get wrong — landmines,
    invariants, and what "done" actually means. It is the field that survives
    you: write what you would tell someone starting this work cold.

    `status` carries the DECISION only — open / shipped / dropped. Progress is
    read from `stage`, never from `status`. external_key makes re-runs
    idempotent (same key updates instead of duplicating). assignee = 'me' or an
    email. Optionally position with after_id/before_id (another slice's id).

    `priority`: 1 (most urgent) to 5, or 0 to clear it. What qualifies for each
    number is `org.priority_policy` from get_project_state — read it first. With
    no policy written, use your own judgement and SAY you did, so a person can
    correct it; those corrections are how the policy gets written."""
    org, user = await require_caller(ctx)

    def _run():
        _, area = _area_arg(org, area_id)
        member = resolve_member(org, assignee, caller_user=user) if assignee else None
        after = _resolve_slice(org, after_id) if after_id is not None else None
        before = _resolve_slice(org, before_id) if before_id is not None else None
        # created_by = who this slice came from; a machine token leaves it NULL
        # and the UI falls back to `source`. The same OrgMember is also what
        # goes on the activity row, so both answer "who" the same way.
        creator = _acting_member(org, user)
        s = _create_slice(
            org, area=area, title=title, spec=spec, constraints=constraints,
            status=status, priority=priority, tags=tags, after=after,
            before=before, source="agent",
            assignee_member=member, external_key=external_key, created_by=creator,
            member=creator,
        )
        return slice_dict(s)

    return await sync_to_async(_run, thread_sensitive=True)()


# A batch may close at most this many slices in one call. The point of the
# batch is that closing should not cost more than capturing did -- 109 slices
# once took 109 calls -- but an unbounded list makes one mistaken argument able
# to close an entire org, and that is too much to buy with a typo.
BATCH_LIMIT = 200

# Fields a batch may set. All three are reversible by design: `status` records
# a decision that can be decided again, clearing or setting an area is
# explicitly two-way, and a priority can be re-set or cleared with 0.
# Everything else a batch could touch destroys text that was written once --
# the same shape as the spec overwrite that permanently erased a decision
# record (TP-238) -- so a batch is not allowed to carry it.
#
# priority belongs here because triage is the case the batch exists for: it is
# the field you are most likely to set across twenty captures at once, and
# making that cost twenty calls is what the batch was built to end.
BATCH_FIELDS = ("status", "area_id", "priority")


@mcp.tool()
async def update_slice(
    ctx: Context,
    slice_id: int | list[int],
    title: str | None = None,
    spec: str | None = None,
    constraints: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    area_id: int | str | None = None,
    tags: list[str] | None = None,
    assignee: str | None = None,
    after_id: int | None = None,
    before_id: int | None = None,
) -> dict:
    """Update a slice. Omitted fields are left alone.

    `spec` is the design doc; write it here once the work has been thought
    through — that is what moves a slice off stage 'needs_design'.
    `constraints` is what a later agent must not get wrong: landmines,
    invariants, and what "done" means.

    `area_id` files the slice: pass an area's id to file it, or '' to send it
    back to the Inbox. Filing is reversible in both directions — it is a
    decision about where work belongs, never about whether it survives.

    `status` records a DECISION (open / shipped / dropped) and nothing else;
    it folds in the old set_slice_status. Never read progress from it — read
    `stage` (list_slices/get_slice report it). after_id/before_id fold in
    reorder. `assignee`: '' clears, 'me' = you, '<email>' = that member.

    `priority`: 1 (most urgent) to 5, or 0 to clear it. What qualifies for each
    number is `org.priority_policy` from get_project_state — read it first. With
    no policy written, use your own judgement and SAY you did, so a person can
    correct it; those corrections are how the policy gets written.

    `slice_id` also takes a LIST, to file or close many slices in one call —
    tidying a board should not cost more per slice than filling it did. A batch
    may set only `status`, `area_id` and `priority`, the reversible decisions;
    passing
    `spec`, `constraints` or `title` with a list is refused rather than applied,
    because one body text written across many slices cannot be undone. Unknown
    ids fail the whole call, so "how many actually closed" is never a guess.
    Returns a dict for a single id and a list for a batch."""
    org, user = await require_caller(ctx)
    batched = isinstance(slice_id, list)
    if batched:
        _reject_unbatchable(
            slice_id, title=title, spec=spec, constraints=constraints,
            after_id=after_id, before_id=before_id, tags=tags, assignee=assignee,
        )

    def _run_one(sid):
        s = _resolve_slice(org, sid)
        moved, area = _area_arg(org, area_id)
        member = resolve_member(org, assignee, caller_user=user) if assignee is not None else None
        after = _resolve_slice(org, after_id) if after_id is not None else None
        before = _resolve_slice(org, before_id) if before_id is not None else None
        # Deliberately not `member` — that one is the ASSIGNEE this call is
        # setting. This is who is doing the setting, and conflating the two
        # would attribute the edit to whoever it was handed to.
        acting = _acting_member(org, user)
        s = _update_slice(
            s, title=title, spec=spec, constraints=constraints, status=status,
            priority=priority, tags=tags, assignee=assignee, assignee_member=member,
            before=before, after=after, source="agent", member=acting,
        )
        if moved:
            # Filing goes through set_slice_area, not a bare field write: it
            # re-ranks the slice into its new area's ordering and records the
            # move on the activity thread. A plain assignment would leave the
            # slice ranked against siblings it no longer has.
            s = _set_slice_area(s, area, source="agent", member=acting)
        return slice_dict(s)

    def _run():
        if not batched:
            return _run_one(slice_id)
        # One transaction: a half-closed batch cannot be retried safely and
        # cannot be reported honestly. Each slice still goes through the same
        # single-slice path, so every one of them gets its own activity row --
        # collapsing a batch into one event would erase from each slice's own
        # history the moment it was closed, and this product's whole claim is
        # that the record survives.
        with transaction.atomic():
            return [_run_one(sid) for sid in slice_id]

    return await sync_to_async(_run, thread_sensitive=True)()


def _reject_unbatchable(ids, **fields):
    """Guard the batch path. Every branch here refuses rather than repairs: a
    batch that silently drops an argument is how one mistaken call rewrites a
    hundred slices and nobody finds out until the text is gone."""
    if not ids:
        raise InvalidValue("slice_id list is empty — nothing to update")
    if len(ids) > BATCH_LIMIT:
        raise InvalidValue(
            f"a batch updates at most {BATCH_LIMIT} slices, got {len(ids)}"
        )
    if len(set(ids)) != len(ids):
        raise InvalidValue("slice_id list contains the same id more than once")
    named = sorted(k for k, v in fields.items() if v is not None)
    if named:
        raise InvalidValue(
            f"a batch may only set {' and '.join(BATCH_FIELDS)}; "
            f"got {', '.join(named)} — update those one slice at a time"
        )


def _public_origin(ctx) -> str:
    """The origin an external shell should call back on.

    Pinned by TUCKIT_OAUTH_ISSUER wherever a deployment sets one -- cloud sits
    behind a proxy, so the request's own Host is the internal address -- and
    derived from the request otherwise, which is what a self-hosted install
    needs and what the OAuth metadata endpoints already do. The same setting,
    because "where does the outside world reach this server" is one fact.

    Scheme: the proxy header first, then the request's own scheme (a bare,
    un-proxied self-hosted install has no `x-forwarded-proto`, and defaulting
    to https there hands back a URL that does not resolve), and only then a
    last-resort "https".
    """
    if settings.TUCKIT_OAUTH_ISSUER:
        return settings.TUCKIT_OAUTH_ISSUER.rstrip("/")
    request = ctx.request_context.request
    headers = request.headers if request is not None else {}
    scheme = (headers.get("x-forwarded-proto")
              or getattr(getattr(request, "url", None), "scheme", None)
              or "https")
    return f"{scheme}://{headers.get('host', '')}".rstrip("/")


@mcp.tool()
async def propose(ctx: Context, slice_id: int, nodes: list[dict]) -> dict:
    """Add nodes to a slice's design canvas while the design is still open.

    The canvas is the slice's thinking surface: a left-to-right tree of cards
    the human watches grow in their browser while you explore. Put each
    question you are weighing up as a `question` node, and every candidate
    answer as an `option` node whose `parent` is that question. `note` is for
    anything that is neither.

    Each node: `id` (yours, unique on this canvas), `parent` (another node's
    id, or null for the single root), `kind` (question|option|note), `title`,
    `summary` (one line), `body` (markdown prose, always visible on the card),
    `media` ([{kind: "image", url, alt, w, h}]), `recommended` (true on the one
    you would take).

    Append-only, and accepted only while `spec` is empty. A branch you explored
    and dropped is part of the record, so nothing is ever edited away -- and
    the record outlives the spec being written, permanently. It is how anyone
    later finds out what was weighed and why the losing options lost, so put
    real reasoning in the bodies rather than labels.

    Writing the spec closes the record to new writes: from then on `propose`
    is rejected while the slice has one. Settle it BEFORE you write, because
    correcting a stale `chosen` afterwards means clearing the spec first.

    Where a node hangs is not a style choice. A node that comes AFTER a
    question was answered must be a child of the option that won it -- those
    nodes exist because of that choice, and hanging them on the question
    instead lets a later re-answer silently re-read them as the result of a
    decision that never produced them. Sending the wrong parent is rejected,
    and the error names the id to use. Extra options may still be added to an
    answered question; what is refused is continuing the story from it.

    Read the record back with `get_slice` (`## Decisions`) before continuing
    someone else's canvas -- that is where the ids and the answers are.

    When the batch contained a question you also get `watch_url`: an
    unauthenticated URL, good for fifteen minutes, that answers
    `{"status": "waiting"}` until someone clicks one of that question's options
    in their browser and `{"status": "chosen", "choice": "<node id>"}` after.
    The id it returns is one of your own, so you already know which option won.
    Poll it from a background shell loop and keep working; never block on it,
    and keep asking the same question in chat, because someone who never opens
    the browser must still be able to answer you. A click chooses a direction --
    it is not approval, and it never stands in for confirmation before writing
    the spec or shipping."""
    org, user = await require_caller(ctx)
    origin = _public_origin(ctx)

    def _run():
        s = _resolve_slice(org, slice_id)
        added = _propose_nodes(s, nodes, source="agent", member=_acting_member(org, user))
        url = ""
        # No question means nothing to wait for. Issuing a watch anyway would
        # leave a row nobody ever reads and hand back a URL that can only ever
        # say "waiting".
        questions = [n for n in added if n.get("kind") == "question"]
        if questions:
            # Scope the watch to the first question node in this batch.
            # Normally there is exactly one -- the skill calls propose per
            # question -- so this covers the common case exactly. If a caller
            # sends several questions in one batch, only the first gets a
            # live watch; the rest are answerable only in chat, because one
            # `propose` call returns only one `watch_url`.
            _, raw = _open_watch(s, question_id=questions[0]["id"])
            url = f"{origin}/watch/{raw}"
        return {"slice_id": s.id, "node_ids": [n["id"] for n in added],
                "count": len(added), "watch_url": url}

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_bites(ctx: Context, slice_id: int) -> list[dict]:
    """List a slice's bites — the ordered implementation steps it was broken
    into, with the status of each. Read this before continuing work someone
    (or some earlier session) already started, so you resume rather than
    restart."""
    org = await require_org(ctx)

    def _run():
        s = _resolve_slice(org, slice_id)
        return [bite_dict(b) for b in _list_bites(s)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def add_bites(ctx: Context, slice_id: int, bites: list[dict]) -> list[dict]:
    """Break a slice into ordered implementation steps. Each item:
    {title, body?, status?}; they are appended in the order given.

    Do this once the slice has a spec — a slice with a spec and no bites reads
    back as stage 'needs_steps', and adding them is what moves it to
    'executing'. Mark each one done with update_bite as you go: that is how a
    human, and the next agent session, can see where the work actually is."""
    org, user = await require_caller(ctx)

    def _run():
        s = _resolve_slice(org, slice_id)
        made = _add_bites(s, bites, source="agent", member=_acting_member(org, user))
        return [bite_dict(b) for b in made]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def update_bite(
    ctx: Context,
    bite_id: int,
    title: str | None = None,
    body: str | None = None,
    status: str | None = None,
    after_id: int | None = None,
    before_id: int | None = None,
) -> dict:
    """Update one implementation step. `status`: todo / doing / done / dropped —
    keep it current as you work, because a slice's stage is derived from how
    many of its bites are done, so a stale checklist misreports the whole
    slice. after_id/before_id fold in reorder."""
    org, user = await require_caller(ctx)

    def _run():
        b = _resolve_bite(org, bite_id)
        after = _resolve_bite(org, after_id) if after_id is not None else None
        before = _resolve_bite(org, before_id) if before_id is not None else None
        return bite_dict(_update_bite(
            b, title=title, body=body, status=status, before=before, after=after, source="agent",
            member=_acting_member(org, user),
        ))

    return await sync_to_async(_run, thread_sensitive=True)()
