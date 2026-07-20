from asgiref.sync import sync_to_async

from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.oauth import resolve_oauth_caller, resolve_oauth_org
from tuckit.core.services.tokens import resolve_org


def _bearer(headers) -> str | None:
    value = headers.get("authorization")
    if not value or not value.lower().startswith("bearer "):
        return None
    return value[len("bearer "):].strip() or None


def _resolve_bearer(raw: str):
    """Additive: OAuth access token first, then legacy ApiToken."""
    return resolve_oauth_org(raw) or resolve_org(raw)


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
                scheme = headers.get("x-forwarded-proto", scope.get("scheme", "https"))
                host = headers.get("host", "")
                prm = f"{scheme}://{host}/.well-known/oauth-protected-resource/mcp"
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate",
                         f'Bearer resource_metadata="{prm}"'.encode("latin-1")),
                    ],
                })
                await send({"type": "http.response.body", "body": b'{"error": "missing bearer token"}'})
                return
        await self.app(scope, receive, send)


async def require_org(ctx):
    """Authoritative auth: resolve the caller's bearer token to an Org, or raise.
    Accepts an OAuth 2.1 access token or a legacy ApiToken (additive)."""
    request = ctx.request_context.request
    raw = _bearer(request.headers) if request is not None else None
    if raw is None:
        raise NotFound("missing bearer token")
    org = await sync_to_async(_resolve_bearer, thread_sensitive=True)(raw)
    if org is None:
        raise NotFound("invalid or unknown API token")
    return org


def _resolve_caller(raw: str):
    """OAuth first (carries a user), then legacy ApiToken (user=None)."""
    oauth = resolve_oauth_caller(raw)
    if oauth is not None:
        return oauth
    org = resolve_org(raw)
    return (org, None) if org is not None else None


async def require_caller(ctx):
    """Resolve the caller's bearer token to (org, user|None), or raise NotFound.
    OAuth tokens carry the acting user; legacy ApiTokens resolve user=None."""
    request = ctx.request_context.request
    raw = _bearer(request.headers) if request is not None else None
    if raw is None:
        raise NotFound("missing bearer token")
    result = await sync_to_async(_resolve_caller, thread_sensitive=True)(raw)
    if result is None:
        raise NotFound("invalid or unknown API token")
    return result
