import contextlib
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tuckit.settings")

from django.core.asgi import get_asgi_application

# get_asgi_application() triggers django.setup(); import model-touching modules AFTER it.
django_asgi_app = get_asgi_application()

from starlette.applications import Starlette  # noqa: E402
from starlette.routing import Mount  # noqa: E402

from tuckit.core.mcp.auth import BearerAuthMiddleware  # noqa: E402
from tuckit.core.mcp.server import _transport_security, mcp  # noqa: E402
from tuckit.core.mcp.transport import AcceptClientNotifications, RefuseSseStream  # noqa: E402

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
# Both transport wrappers sit INSIDE the auth gate on purpose -- see their
# docstrings: an unauthenticated request must still get the 401 that carries
# OAuth discovery, rather than a 405 or a 202 that hides it.
mcp_app = BearerAuthMiddleware(
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


@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield


_starlette_app = Starlette(
    routes=[
        Mount("/mcp", app=mcp_app),
        Mount("/", app=django_asgi_app),
    ],
    lifespan=lifespan,
)


async def app(scope, receive, send):
    """Normalize the bare "/mcp" path to "/mcp/" before routing.

    Starlette's `Mount("/mcp", ...)` only matches paths with something after the
    prefix (i.e. "/mcp/..."), not the bare "/mcp" itself. Since `Mount("/", ...)`
    for Django matches *any* path (including "/mcp"), a bare "/mcp" request would
    otherwise silently fall through to Django instead of reaching the MCP app.
    MCP clients (and this project's own tests) call the bare "/mcp" URL, so we
    rewrite it here rather than relying on Starlette's redirect_slashes (which
    never triggers, since the Django catch-all mount already produces a full
    match before any redirect logic runs).
    """
    if scope["type"] == "http" and scope["path"] == "/mcp":
        scope = {**scope, "path": "/mcp/"}
    await _starlette_app(scope, receive, send)
