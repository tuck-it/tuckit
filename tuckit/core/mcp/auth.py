from asgiref.sync import sync_to_async

from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.tokens import resolve_workspace


def _bearer(headers) -> str | None:
    value = headers.get("authorization")
    if not value or not value.lower().startswith("bearer "):
        return None
    return value[len("bearer "):].strip() or None


class BearerAuthMiddleware:
    """Raw ASGI gate: reject HTTP requests with no bearer token before they reach MCP.
    Implemented as pure ASGI (NOT BaseHTTPMiddleware) so it never buffers MCP's
    streaming/SSE responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            if _bearer(headers) is None:
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({"type": "http.response.body", "body": b'{"error": "missing bearer token"}'})
                return
        await self.app(scope, receive, send)


async def require_workspace(ctx):
    """Authoritative auth: resolve the caller's bearer token to a Workspace, or raise."""
    request = ctx.request_context.request
    raw = _bearer(request.headers) if request is not None else None
    if raw is None:
        raise NotFound("missing bearer token")
    workspace = await sync_to_async(resolve_workspace, thread_sensitive=True)(raw)
    if workspace is None:
        raise NotFound("invalid or unknown API token")
    return workspace
