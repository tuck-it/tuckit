import os

from asgiref.sync import sync_to_async
from mcp.server.fastmcp import Context, FastMCP
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
from tuckit.core.services.resolve import get_area
from tuckit.core.services.resolve import get_bite as _resolve_bite
from tuckit.core.services.resolve import get_slice as _resolve_slice
from tuckit.core.services.resolve import get_slice_flexible as _resolve_slice_flexible
from tuckit.core.services.members import resolve_member
from tuckit.core.services.slices import create_slice as _create_slice
from tuckit.core.services.slices import query_slices as _query_slices
from tuckit.core.services.slices import set_slice_area as _set_slice_area
from tuckit.core.services.slices import stage_of
from tuckit.core.services.slices import update_slice as _update_slice
from tuckit.core.services.state import get_project_state as _get_project_state
from tuckit.core.services.state import render_slice_markdown

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

# Run the Streamable HTTP transport in STATELESS mode. The default (stateful)
# mode keeps per-session state in the serving process's local memory and issues
# an Mcp-Session-Id that every follow-up request must carry back to *that same*
# process. That assumes one long-lived process (as with stdio) and breaks on any
# horizontally-scaled / ephemeral host: a follow-up request that lands on a
# different instance -- or after the instance holding the session is reaped (e.g.
# a serverless deploy scaling to zero on idle) -- can't find its session and
# 4xxs, which MCP clients surface as a dropped connection. Stateless mode makes
# each request self-contained, so any instance can serve it and no session is
# lost. This is safe here because the server exposes only plain request/response
# tools -- no server-initiated notifications, sampling, or subscriptions, which
# are the only things stateful mode would buy. (Add those back only alongside an
# out-of-process session/event store; don't rely on in-memory sessions.)
mcp = FastMCP(
    "tuck-it",
    json_response=True,
    stateless_http=True,
    streamable_http_path="/",
    transport_security=_transport_security,
)


@mcp.tool()
async def get_project_state(ctx: Context, area_id: int | None = None) -> dict:
    """Current project state (shipped/roadmap) plus the caller's identity
    (user_email, org). Optionally scope to one area by id.

    `inbox` counts the slices that have no area yet — things someone decided
    mattered before deciding where they belong. They are real slices, not a
    separate kind of object: give one an area (update_slice) and it joins that
    area's roadmap; clear the area and it comes back."""
    org, user = await require_caller(ctx)

    def _run():
        area = get_area(org, area_id) if area_id is not None else None
        return _get_project_state(org, area=area, caller_user=user)

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
    `stage`; `status` only ever records a decision (open/shipped/dropped)."""
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
        return [{**slice_dict(s), "stage": stage_of(s)} for s in rows]

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
    email. Optionally position with after_id/before_id (another slice's id)."""
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
            status=status, tags=tags, after=after, before=before, source="agent",
            assignee_member=member, external_key=external_key, created_by=creator,
            member=creator,
        )
        return slice_dict(s)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def update_slice(
    ctx: Context,
    slice_id: int,
    title: str | None = None,
    spec: str | None = None,
    constraints: str | None = None,
    status: str | None = None,
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
    reorder. `assignee`: '' clears, 'me' = you, '<email>' = that member."""
    org, user = await require_caller(ctx)

    def _run():
        s = _resolve_slice(org, slice_id)
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
            tags=tags, assignee=assignee, assignee_member=member,
            before=before, after=after, source="agent", member=acting,
        )
        if moved:
            # Filing goes through set_slice_area, not a bare field write: it
            # re-ranks the slice into its new area's ordering and records the
            # move on the activity thread. A plain assignment would leave the
            # slice ranked against siblings it no longer has.
            s = _set_slice_area(s, area, source="agent", member=acting)
        return slice_dict(s)

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
