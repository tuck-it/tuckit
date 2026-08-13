from dataclasses import dataclass

from asgiref.sync import sync_to_async

from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.oauth import resolve_oauth_caller
from tuckit.core.services.tokens import resolve_org_token


def _bearer(headers) -> str | None:
    value = headers.get("authorization")
    if not value or not value.lower().startswith("bearer "):
        return None
    return value[len("bearer "):].strip() or None


@dataclass(frozen=True)
class Connection:
    """Who is on the other end of one MCP request.

    `key` identifies the agent connection across access-token rotation. An
    OAuth access token lives one hour and its refresh rotates on use, so the
    token string is useless as an identity; (client, user, org) is not.

    `label` is for humans reading an operator page, so it never contains a
    token or a hash.
    """
    org: object
    user: object | None
    key: tuple
    label: str


def _connection(raw: str) -> Connection | None:
    """Resolve a bearer string to a Connection. OAuth first, then the legacy
    ApiToken, which carries neither a client nor a user and legitimately keys
    on itself."""
    found = resolve_oauth_caller(raw)
    if found is not None:
        org, user, client = found
        return Connection(
            org=org,
            user=user,
            key=("oauth", client.id, user.id, org.id),
            label=f"{client.name or client.client_id} · {user.email}",
        )
    token = resolve_org_token(raw)
    if token is not None:
        return Connection(
            org=token.org,
            user=None,
            key=("apitoken", token.id),
            label=f"API token #{token.id}",
        )
    return None


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


async def _require_connection(ctx) -> Connection:
    """Authoritative auth for one MCP request. Bite 3 adds the rate check here,
    which is why the tools' own entry points do not need the key."""
    request = ctx.request_context.request
    raw = _bearer(request.headers) if request is not None else None
    if raw is None:
        raise NotFound("missing bearer token")
    conn = await sync_to_async(_connection, thread_sensitive=True)(raw)
    if conn is None:
        raise NotFound("invalid or unknown API token")
    return conn


async def require_org(ctx):
    """Resolve the caller's bearer token to an Org, or raise."""
    conn = await _require_connection(ctx)
    return conn.org


async def require_caller(ctx):
    """Resolve the caller's bearer token to (org, user|None), or raise. OAuth
    tokens carry the acting user; legacy ApiTokens resolve user=None."""
    conn = await _require_connection(ctx)
    return conn.org, conn.user
