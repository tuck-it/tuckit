import contextlib
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tuckit.settings")

from django.core.asgi import get_asgi_application

# get_asgi_application() triggers django.setup(); import model-touching modules AFTER it.
django_asgi_app = get_asgi_application()

from starlette.applications import Starlette  # noqa: E402
from starlette.routing import Mount  # noqa: E402

from tuckit.core.mcp.auth import BearerAuthMiddleware  # noqa: E402
from tuckit.core.mcp.server import mcp  # noqa: E402

mcp_app = BearerAuthMiddleware(mcp.streamable_http_app())


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
