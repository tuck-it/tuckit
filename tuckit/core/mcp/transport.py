"""Transport-shaped policy that sits between the auth gate and the MCP app."""
import json

# Kept in the body so an operator reading a 405 in the logs knows it is a
# deliberate answer and not a routing accident.
NO_SSE = (
    "this server does not offer an SSE stream at this endpoint; "
    "send requests as HTTP POST"
)


class RefuseSseStream:
    """Answer `GET /mcp` with 405 instead of opening a standalone SSE stream.

    A Streamable HTTP client opens a long-lived GET stream after initialize so
    the server can push requests and notifications to it. This server has
    nothing to push: it runs stateless (see tuckit/asgi.py) and exposes only
    plain request/response tools -- no server-initiated notifications, no
    sampling, no subscriptions. Left to the SDK, that stream opens anyway and
    then sends a `: ping` comment every 15 seconds, forever, carrying nothing.

    That idle stream is not free, it is the failure. app.tuckit.dev sits behind
    infrastructure that closes an idle HTTP connection after 240 seconds
    (measured against production, 2026-08-15), and a client whose stream dies
    treats the whole transport as dead -- every later tool call then fails
    instantly with "the connection is closed" without a request ever leaving
    the machine. Refusing the stream removes the only long-lived thing in an
    architecture that cannot host one; POST round-trips are unaffected, and
    each one is self-contained.

    405 is the spec's own answer here: "the server MAY return 405 Method Not
    Allowed, indicating that the server does not offer an SSE stream at this
    endpoint." Clients treat it as "SSE unsupported" and keep using POST, so
    this is a supported configuration rather than a degraded one.

    Ordering matters. This must sit INSIDE BearerAuthMiddleware, so that an
    unauthenticated GET still gets 401 with the `WWW-Authenticate:
    Bearer resource_metadata=...` header that drives OAuth discovery. Answering
    405 before authenticating would strip that header off a request some
    clients use to find the authorization server.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "GET":
            await send({
                "type": "http.response.start",
                "status": 405,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"allow", b"POST"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": json.dumps({"error": NO_SSE}).encode("utf-8"),
            })
            return
        await self.app(scope, receive, send)
