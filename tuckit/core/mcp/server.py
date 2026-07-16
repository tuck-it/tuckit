import os

from asgiref.sync import sync_to_async
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from tuckit.core.mcp.auth import require_workspace
from tuckit.core.mcp.serializers import area_dict, bite_dict, slice_dict
from tuckit.core.services.areas import create_area as _create_area
from tuckit.core.services.areas import list_areas as _list_areas
from tuckit.core.services.bites import (
    create_bite as _create_bite,
    list_bites as _list_bites,
    reorder_bite as _reorder_bite,
    set_bite_status as _set_bite_status,
    update_bite as _update_bite,
)
from tuckit.core.services.plans import set_plan as _set_plan
from tuckit.core.services.resolve import get_area
from tuckit.core.services.resolve import get_bite as _resolve_bite
from tuckit.core.services.resolve import get_slice as _resolve_slice
from tuckit.core.services.slices import create_slice as _create_slice
from tuckit.core.services.slices import list_slices as _list_slices
from tuckit.core.services.slices import reorder_slice as _reorder_slice
from tuckit.core.services.slices import set_slice_status as _set_slice_status
from tuckit.core.services.slices import update_slice as _update_slice
from tuckit.core.services.state import get_project_state as _get_project_state
from tuckit.core.services.state import render_slice_markdown
from tuckit.core.services.tags import list_tags as _list_tags

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


def _project_state(workspace, area_id: int | None) -> dict:
    area = get_area(workspace, area_id) if area_id is not None else None
    return _get_project_state(workspace, area=area)


@mcp.tool()
async def get_project_state(ctx: Context, area_id: int | None = None) -> dict:
    """Return the current project state (shipped / building / roadmap / ideas / someday),
    assembled live from the workspace's slices and bites. Optionally scope to one area by id."""
    workspace = await require_workspace(ctx)
    return await sync_to_async(_project_state, thread_sensitive=True)(workspace, area_id)


@mcp.tool()
async def list_areas(ctx: Context) -> list[dict]:
    """List the workspace's areas (long-lived responsibility domains, e.g. backend/frontend)."""
    workspace = await require_workspace(ctx)

    def _run():
        return [area_dict(a) for a in _list_areas(workspace)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_area(ctx: Context, name: str, description: str = "") -> dict:
    """Create a new area in the workspace."""
    workspace = await require_workspace(ctx)

    def _run():
        return area_dict(_create_area(workspace, name, description=description))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_tags(ctx: Context) -> list[str]:
    """List all tag names defined in the workspace."""
    workspace = await require_workspace(ctx)

    def _run():
        return [t.name for t in _list_tags(workspace)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_slices(ctx: Context, area_id: int, status: str | None = None, tag: str | None = None) -> list[dict]:
    """List slices in an area, optionally filtered by status or tag name."""
    workspace = await require_workspace(ctx)

    def _run():
        area = get_area(workspace, area_id)
        return [slice_dict(s) for s in _list_slices(area, status=status, tag=tag)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def get_slice(ctx: Context, slice_id: int) -> str:
    """Return a slice rendered as markdown (its spec plus a bite checklist)."""
    workspace = await require_workspace(ctx)

    def _run():
        return render_slice_markdown(_resolve_slice(workspace, slice_id))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def set_plan(ctx: Context, slice_id: int, body: str | None = None, constraints: str | None = None) -> str:
    """Set the slice's plan — an overview (`body`) and global `constraints`.
    Omitted fields are left unchanged. Returns the slice rendered as markdown."""
    workspace = await require_workspace(ctx)

    def _run():
        s = _resolve_slice(workspace, slice_id)
        _set_plan(s, body=body, constraints=constraints, actor="agent")
        return render_slice_markdown(s)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_slice(
    ctx: Context,
    area_id: int,
    title: str,
    spec: str = "",
    status: str = "idea",
    tags: list[str] | None = None,
    after_id: int | None = None,
    before_id: int | None = None,
) -> dict:
    """Create a slice in an area. Use status='idea' for a quick capture ('do this next session').
    Optionally position it with after_id/before_id (another slice's id in the same area)."""
    workspace = await require_workspace(ctx)

    def _run():
        area = get_area(workspace, area_id)
        after = _resolve_slice(workspace, after_id) if after_id is not None else None
        before = _resolve_slice(workspace, before_id) if before_id is not None else None
        s = _create_slice(
            area, title, spec=spec, status=status, tags=tags,
            after=after, before=before, source="agent",
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
) -> dict:
    """Update a slice's title, spec, status, and/or tags (tags replace the existing set)."""
    workspace = await require_workspace(ctx)

    def _run():
        s = _resolve_slice(workspace, slice_id)
        return slice_dict(_update_slice(s, title=title, spec=spec, status=status, tags=tags, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def set_slice_status(ctx: Context, slice_id: int, status: str) -> dict:
    """Set a slice's status (idea/planned/building/shipped/dropped)."""
    workspace = await require_workspace(ctx)

    def _run():
        return slice_dict(_set_slice_status(_resolve_slice(workspace, slice_id), status, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def reorder_slice(ctx: Context, slice_id: int, after_id: int | None = None, before_id: int | None = None) -> dict:
    """Move a slice to just after (after_id) or just before (before_id) another slice in its area."""
    workspace = await require_workspace(ctx)

    def _run():
        s = _resolve_slice(workspace, slice_id)
        after = _resolve_slice(workspace, after_id) if after_id is not None else None
        before = _resolve_slice(workspace, before_id) if before_id is not None else None
        return slice_dict(_reorder_slice(s, after=after, before=before))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def list_bites(ctx: Context, slice_id: int) -> list[dict]:
    """List the bites (implementation steps) of a slice."""
    workspace = await require_workspace(ctx)

    def _run():
        s = _resolve_slice(workspace, slice_id)
        return [bite_dict(b) for b in _list_bites(s)]

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def create_bite(
    ctx: Context,
    slice_id: int,
    title: str,
    body: str = "",
    status: str = "todo",
    after_id: int | None = None,
    before_id: int | None = None,
) -> dict:
    """Add a bite (implementation step) to a slice, optionally positioned with after_id/before_id."""
    workspace = await require_workspace(ctx)

    def _run():
        s = _resolve_slice(workspace, slice_id)
        after = _resolve_bite(workspace, after_id) if after_id is not None else None
        before = _resolve_bite(workspace, before_id) if before_id is not None else None
        b = _create_bite(s, title, body=body, status=status, after=after, before=before, source="agent")
        return bite_dict(b)

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def update_bite(
    ctx: Context,
    bite_id: int,
    title: str | None = None,
    body: str | None = None,
    status: str | None = None,
) -> dict:
    """Update a bite's title, body, and/or status."""
    workspace = await require_workspace(ctx)

    def _run():
        b = _resolve_bite(workspace, bite_id)
        return bite_dict(_update_bite(b, title=title, body=body, status=status, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def set_bite_status(ctx: Context, bite_id: int, status: str) -> dict:
    """Set a bite's status (todo/doing/done/dropped)."""
    workspace = await require_workspace(ctx)

    def _run():
        return bite_dict(_set_bite_status(_resolve_bite(workspace, bite_id), status, actor="agent"))

    return await sync_to_async(_run, thread_sensitive=True)()


@mcp.tool()
async def reorder_bite(ctx: Context, bite_id: int, after_id: int | None = None, before_id: int | None = None) -> dict:
    """Move a bite to just after (after_id) or just before (before_id) another bite in its slice."""
    workspace = await require_workspace(ctx)

    def _run():
        b = _resolve_bite(workspace, bite_id)
        after = _resolve_bite(workspace, after_id) if after_id is not None else None
        before = _resolve_bite(workspace, before_id) if before_id is not None else None
        return bite_dict(_reorder_bite(b, after=after, before=before))

    return await sync_to_async(_run, thread_sensitive=True)()
