"""Assemble the ASGI app that serves the MCP endpoint alongside Django.

This module is the single place the composition lives. Every entrypoint --
`tuckit.asgi` here, `tuckit_cloud.asgi` in the private cloud layer, and any
future one -- calls `build_asgi_app()` and mounts nothing itself. That is a
correctness requirement, not tidiness: the two entrypoints used to be
hand-maintained copies of each other, production served only the cloud one,
and a change made in the core shipped nowhere while both repos' tests stayed
green. It happened in two consecutive releases (v0.53.0: the transport options
moved into `streamable_http_app()` and the copy kept calling it bare, so every
`/mcp` request 404'd; v0.54.0: `AcceptClientNotifications` was added here only,
so production kept answering 400 to client notifications and dropping agents
mid-session). With nothing left to copy, there is nothing left to drift.

Anything deployment-specific must arrive as an argument or through settings --
the allowed hosts and OAuth issuer, for instance, already reach
`_transport_security` from the environment. Nothing cloud-specific may be
hardcoded here: this file is part of the public core.
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from tuckit.core.mcp.auth import BearerAuthMiddleware
from tuckit.core.mcp.server import _transport_security, mcp
from tuckit.core.mcp.transport import (
    AcceptClientNotifications,
    RefuseSseStream,
    ResetDatabaseConnections,
)

MCP_PREFIX = "/mcp"


def build_mcp_app():
    """The MCP transport app, wrapped in the policy stack that has to sit around it.

    Every argument below is load-bearing, and none may be dropped to "take the
    defaults". Under mcp 1.x these lived on the `FastMCP()` constructor, so a
    bare `streamable_http_app()` call inherited them; under 2.x they live here
    and the defaults are all wrong for this deployment:

    - `streamable_http_path` defaults to "/mcp", but the caller mounts this app
      under "/mcp" and the prefix is already stripped by then, so the route
      would land at "/mcp/mcp" and every request 404s;
    - `stateless_http` defaults to False, which restores the in-memory sessions
      described below;
    - `transport_security` defaults to None, disabling DNS-rebinding protection.

    Run the Streamable HTTP transport in STATELESS mode. The default (stateful)
    mode keeps per-session state in the serving process's local memory and
    issues an Mcp-Session-Id that every follow-up request must carry back to
    *that same* process. That assumes one long-lived process (as with stdio) and
    breaks on any horizontally-scaled / ephemeral host: a follow-up request that
    lands on a different instance -- or after the instance holding the session
    is reaped (e.g. a serverless deploy scaling to zero on idle) -- can't find
    its session and 4xxs, which MCP clients surface as a dropped connection.
    Stateless mode makes each request self-contained, so any instance can serve
    it and no session is lost. This is safe here because the server exposes only
    plain request/response tools -- no server-initiated notifications, sampling,
    or subscriptions, which are the only things stateful mode would buy. (Add
    those back only alongside an out-of-process session/event store; don't rely
    on in-memory sessions.)

    Both transport wrappers sit INSIDE the auth gate on purpose -- see their
    docstrings: an unauthenticated request must still get the 401 that carries
    OAuth discovery, rather than a 405 or a 202 that hides it.

    ResetDatabaseConnections sits OUTSIDE it, for the mirror-image reason:
    checking a bearer token is a database query, so a connection that died while
    the process was idle has to be reaped before the auth gate runs, not after.
    """
    return ResetDatabaseConnections(
        BearerAuthMiddleware(
            RefuseSseStream(
                AcceptClientNotifications(
                    mcp.streamable_http_app(
                        streamable_http_path="/",
                        json_response=True,
                        stateless_http=True,
                        transport_security=_transport_security,
                    )
                )
            )
        )
    )


def build_asgi_app(django_asgi_app):
    """The whole ASGI app: MCP under "/mcp", Django everywhere else.

    `django_asgi_app` is passed in rather than built here because each
    entrypoint boots Django with its own settings module, and
    `get_asgi_application()` has to run before any model-touching import.

    The returned callable is what an ASGI server serves.
    """
    mcp_app = build_mcp_app()

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        # `session_manager.run()` may only be entered once per FastMCP
        # instance, and `mcp` is a module-level singleton -- so building a
        # second app in one process (as tests do) requires reimporting
        # `tuckit.core.mcp.*` rather than just calling this again.
        async with mcp.session_manager.run():
            yield

    starlette_app = Starlette(
        routes=[
            Mount(MCP_PREFIX, app=mcp_app),
            Mount("/", app=django_asgi_app),
        ],
        lifespan=lifespan,
    )

    async def app(scope, receive, send):
        """Normalize the bare "/mcp" path to "/mcp/" before routing.

        Starlette's `Mount("/mcp", ...)` only matches paths with something after
        the prefix (i.e. "/mcp/..."), not the bare "/mcp" itself. Since
        `Mount("/", ...)` for Django matches *any* path (including "/mcp"), a
        bare "/mcp" request would otherwise silently fall through to Django
        instead of reaching the MCP app. MCP clients (and this project's own
        tests) call the bare "/mcp" URL, so we rewrite it here rather than
        relying on Starlette's redirect_slashes (which never triggers, since the
        Django catch-all mount already produces a full match before any redirect
        logic runs).
        """
        if scope["type"] == "http" and scope["path"] == MCP_PREFIX:
            scope = {**scope, "path": f"{MCP_PREFIX}/"}
        await starlette_app(scope, receive, send)

    return app
