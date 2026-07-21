import os

from asgiref.sync import sync_to_async
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from tuckit.core.mcp.auth import require_caller, require_org
from tuckit.core.mcp.serializers import activity_event_dict, area_dict, bite_dict, plan_dict, slice_dict, ticket_dict
from tuckit.core.services.activity import add_note as _add_note
from tuckit.core.services.areas import create_area as _create_area
from tuckit.core.services.areas import list_areas as _list_areas
from tuckit.core.services.bites import (
    add_bites as _add_bites,
    list_bites as _list_bites,
    update_bite as _update_bite,
)
from tuckit.core.services.plans import create_plan as _create_plan
from tuckit.core.services.plans import list_plans as _list_plans
from tuckit.core.services.plans import update_plan as _update_plan
from tuckit.core.services.resolve import get_area
from tuckit.core.services.resolve import get_bite as _resolve_bite
from tuckit.core.services.resolve import get_plan as _resolve_plan
from tuckit.core.services.resolve import get_slice as _resolve_slice
from tuckit.core.services.resolve import get_slice_flexible as _resolve_slice_flexible
from tuckit.core.services.resolve import get_ticket as _resolve_ticket
from tuckit.core.services.members import resolve_member
from tuckit.core.services.slices import create_slice as _create_slice
from tuckit.core.services.slices import query_slices as _query_slices
from tuckit.core.services.slices import stage_of
from tuckit.core.services.slices import update_slice as _update_slice
from tuckit.core.services.state import get_project_state as _get_project_state
from tuckit.core.services.state import render_slice_markdown, render_ticket_markdown
from tuckit.core.services.tickets import (
    create_ticket as _create_ticket,
    query_tickets as _query_tickets,
    update_ticket as _update_ticket,
    promote_ticket as _promote_ticket,
    absorb_ticket as _absorb_ticket,
    release_ticket as _release_ticket,
)

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
    """Current project state (shipped/building/roadmap/ideas/someday) plus the
    caller's identity (user_email, org). Optionally scope to one area by id."""
    org, user = await require_caller(ctx)

    def _run():
        area = get_area(org, area_id) if area_id is not None else None
        return _get_project_state(org, area=area, caller_user=user)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_areas(ctx: Context) -> list[dict]:
    """List the org's areas (long-lived responsibility domains, e.g. backend/frontend)."""
    org = await require_org(ctx)

    def _run():
        return [area_dict(a) for a in _list_areas(org)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_area(ctx: Context, name: str, description: str = "") -> dict:
    """Create a new area in the org."""
    org = await require_org(ctx)

    def _run():
        return area_dict(_create_area(org, name, description=description))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_slices(
    ctx: Context,
    area_id: int | None = None,
    status: str | None = None,
    tag: str | None = None,
    query: str | None = None,
    assignee: str | None = None,
    limit: int | None = 50,
) -> list[dict]:
    """List/search slices. All filters optional; with no area_id it searches the
    whole org. query = text match on title/spec. assignee = 'me' or an email.

    Each row carries `stage` — what that slice needs next, derived from its own
    state: needs_design (spec is empty — brainstorm and write the design doc into
    it), needs_plan, needs_bites (a plan exists but has no steps), executing,
    ready_to_ship, or shipped/dropped for finished work."""
    org, user = await require_caller(ctx)

    def _run():
        area = get_area(org, area_id) if area_id is not None else None
        member = resolve_member(org, assignee, caller_user=user) if assignee else None
        rows = _query_slices(
            org, area=area, status=status, tag=tag, query=query,
            assignee_member=member, limit=limit,
        )
        # Merged here rather than inside slice_dict(): that serializer is shared
        # with create/update/promote, which already know what they just wrote.
        return [{**slice_dict(s), "stage": stage_of(s)} for s in rows]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def get_slice(ctx: Context, slice: int | str, with_activity: bool = False) -> str:
    """Return a slice rendered as markdown (spec + bite checklist). `slice` may be
    a numeric id or a ref like 'tuck-it-42'. Set with_activity=true to append the
    activity/notes thread.

    The `Stage:` line says what to do next: needs_design (spec is empty —
    brainstorm and write the design doc into it), needs_plan, needs_bites (a plan
    exists but has no steps), executing, ready_to_ship, or shipped/dropped."""
    org = await require_org(ctx)

    def _run():
        s = _resolve_slice_flexible(org, slice)
        return render_slice_markdown(s, with_activity=with_activity)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def add_note(ctx: Context, slice: int | str, body: str) -> dict:
    """Append a free-text note to a slice's activity thread (what you did, blockers,
    PR links). `slice` may be an id or a ref."""
    org = await require_org(ctx)

    def _run():
        s = _resolve_slice_flexible(org, slice)
        return activity_event_dict(_add_note(s, body, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_plan(
    ctx: Context, slice_id: int, title: str = "", body: str = "", constraints: str = ""
) -> dict:
    """Create a plan under a slice (a slice may hold multiple plans, each with its
    own title, overview `body`, and `constraints`)."""
    org = await require_org(ctx)

    def _run():
        s = _resolve_slice(org, slice_id)
        return plan_dict(_create_plan(s, title=title, body=body, constraints=constraints, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_plans(ctx: Context, slice_id: int) -> list[dict]:
    """List the plans under a slice."""
    org = await require_org(ctx)

    def _run():
        s = _resolve_slice(org, slice_id)
        return [plan_dict(p) for p in _list_plans(s)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def update_plan(
    ctx: Context,
    plan_id: int,
    title: str | None = None,
    body: str | None = None,
    constraints: str | None = None,
) -> dict:
    """Update a plan's title, overview `body`, and/or `constraints`. Omitted fields
    are left unchanged."""
    org = await require_org(ctx)

    def _run():
        plan = _resolve_plan(org, plan_id)
        return plan_dict(_update_plan(plan, title=title, body=body, constraints=constraints, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_slice(
    ctx: Context,
    area_id: int,
    title: str,
    spec: str = "",
    status: str = "planned",
    tags: list[str] | None = None,
    assignee: str | None = None,
    external_key: str = "",
    after_id: int | None = None,
    before_id: int | None = None,
) -> dict:
    """Create a slice directly in an area (default status 'planned'). For quick,
    unfiled capture use create_ticket instead. external_key makes re-runs idempotent
    (same key updates instead of duplicating). assignee = 'me' or an email. Optionally
    position with after_id/before_id (another slice's id in the same area)."""
    org, user = await require_caller(ctx)

    def _run():
        area = get_area(org, area_id)
        member = resolve_member(org, assignee, caller_user=user) if assignee else None
        after = _resolve_slice(org, after_id) if after_id is not None else None
        before = _resolve_slice(org, before_id) if before_id is not None else None
        s = _create_slice(
            area, title, spec=spec, status=status, tags=tags,
            after=after, before=before, source="agent",
            assignee_member=member, external_key=external_key,
        )
        return slice_dict(s)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def update_slice(
    ctx: Context,
    slice_id: int,
    title: str | None = None,
    spec: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    assignee: str | None = None,
    after_id: int | None = None,
    before_id: int | None = None,
) -> dict:
    """Update a slice. `status` folds in the old set_slice_status; after_id/before_id
    fold in reorder. `assignee`: '' clears, 'me' = you, '<email>' = that member."""
    org, user = await require_caller(ctx)

    def _run():
        s = _resolve_slice(org, slice_id)
        member = resolve_member(org, assignee, caller_user=user) if assignee is not None else None
        after = _resolve_slice(org, after_id) if after_id is not None else None
        before = _resolve_slice(org, before_id) if before_id is not None else None
        return slice_dict(_update_slice(
            s, title=title, spec=spec, status=status, tags=tags,
            assignee=assignee, assignee_member=member, before=before, after=after,
            actor="agent",
        ))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_tickets(
    ctx: Context,
    status: str = "open",
    area_id: int | None = None,
    query: str | None = None,
    limit: int | None = 50,
) -> list[dict]:
    """List backlog tickets (default: open = the Inbox). A ticket is a lightweight
    capture upstream of a slice; promote one to start work. status: 'open',
    'promoted', 'dismissed', 'duplicate' — or '' for all."""
    org = await require_org(ctx)

    def _run():
        area = get_area(org, area_id) if area_id is not None else None
        rows = _query_tickets(org, status=status, area=area, query=query, limit=limit)
        return [ticket_dict(t) for t in rows]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_ticket(
    ctx: Context, title: str, body: str = "", area_id: int | None = None,
    external_key: str = "",
) -> dict:
    """Capture a backlog ticket (title + optional markdown body). Lands in the
    Inbox (no area) unless area_id is given. Promote it later to create a slice.
    external_key makes re-runs idempotent — pass a stable id (e.g. the source
    TODO or issue key) and a repeat call returns the same ticket."""
    org, user = await require_caller(ctx)

    def _run():
        area = get_area(org, area_id) if area_id is not None else None
        member = resolve_member(org, "me", caller_user=user) if user is not None else None
        t = _create_ticket(org, title, body=body, area=area, source="agent",
                           created_by=member, external_key=external_key)
        return ticket_dict(t)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def get_ticket(ctx: Context, ticket_id: int) -> str:
    """Return a ticket rendered as markdown (title + body + status)."""
    org = await require_org(ctx)

    def _run():
        t = _resolve_ticket(org, ticket_id)
        return render_ticket_markdown(t)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def update_ticket(
    ctx: Context,
    ticket_id: int,
    title: str | None = None,
    body: str | None = None,
    status: str | None = None,
    area_id: int | None = None,
) -> dict:
    """Update a ticket. status: 'dismissed' (decided against) or 'duplicate' —
    both end the ticket. Use promote_ticket to turn one into a slice; a ticket's
    status never tracks delivery. area_id files it under a project (omit to
    leave unchanged)."""
    org = await require_org(ctx)

    def _run():
        t = _resolve_ticket(org, ticket_id)
        kwargs = {"title": title, "body": body, "status": status, "actor": "agent"}
        if area_id is not None:
            kwargs["area"] = get_area(org, area_id)
        return ticket_dict(_update_ticket(t, **kwargs))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def promote_ticket(ctx: Context, ticket_id: int, area_id: int | None = None) -> dict:
    """Promote a ticket into a planned slice (inherits the ticket's ref).
    The slice starts with an EMPTY spec: that blank is how the workflow knows the
    work has not been designed yet, so write the design doc into it before
    planning. The ticket keeps its body — read it via get_ticket, or the 'From:'
    line on the slice. The ticket becomes 'promoted' and the slice owns progress
    from then on. Idempotent — re-promoting returns the existing slice. area_id
    is required only if the ticket has no area yet."""
    org = await require_org(ctx)

    def _run():
        t = _resolve_ticket(org, ticket_id)
        area = get_area(org, area_id) if area_id is not None else None
        return slice_dict(_promote_ticket(t, area=area, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def absorb_ticket(ctx: Context, ticket_id: int, into_slice: int | str) -> dict:
    """Fold an open ticket into an EXISTING slice instead of giving it its own.
    Use when a capture turns out to be part of work already planned. The ticket
    becomes 'promoted' and keeps its own ref; no slice is created and no number
    changes hands. `into_slice` may be an id or a ref."""
    org = await require_org(ctx)

    def _run():
        t = _resolve_ticket(org, ticket_id)
        s = _resolve_slice_flexible(org, into_slice)
        return ticket_dict(_absorb_ticket(t, s, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def release_ticket(ctx: Context, ticket_id: int) -> dict:
    """Undo an absorb: detach the ticket from its slice and return it to the
    Inbox. Absorbed tickets only — the origin ticket gave the slice its ref and
    cannot be released; drop the slice instead."""
    org = await require_org(ctx)

    def _run():
        return ticket_dict(_release_ticket(_resolve_ticket(org, ticket_id), actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_bites(ctx: Context, plan_id: int) -> list[dict]:
    """List the bites (implementation steps) of a plan."""
    org = await require_org(ctx)

    def _run():
        plan = _resolve_plan(org, plan_id)
        return [bite_dict(b) for b in _list_bites(plan)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def add_bites(ctx: Context, plan_id: int, bites: list[dict]) -> list[dict]:
    """Add one or more bites (implementation steps) to a plan, in order.
    Each item: {title, body?, status?}."""
    org = await require_org(ctx)

    def _run():
        plan = _resolve_plan(org, plan_id)
        return [bite_dict(b) for b in _add_bites(plan, bites, source="agent")]

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
    """Update a bite. status folds in set_bite_status; after_id/before_id fold in reorder."""
    org = await require_org(ctx)

    def _run():
        b = _resolve_bite(org, bite_id)
        after = _resolve_bite(org, after_id) if after_id is not None else None
        before = _resolve_bite(org, before_id) if before_id is not None else None
        return bite_dict(_update_bite(
            b, title=title, body=body, status=status, before=before, after=after, actor="agent",
        ))

    return await sync_to_async(_run, thread_sensitive=True)()
