"""Transport-shaped policy that sits between the auth gate and the MCP app."""
import json

from asgiref.sync import sync_to_async
from django.db import close_old_connections

# Bound once. thread_sensitive=True is load-bearing: see ResetDatabaseConnections.
_close_old_connections = sync_to_async(close_old_connections, thread_sensitive=True)

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
    nothing to push: it runs stateless (see compose.py) and exposes only
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


def _is_notification(decoded) -> bool:
    """True for a JSON-RPC body that expects no reply.

    A notification is a message with no `id` member -- not one whose id is
    null, which is why this tests for the key rather than its value. A batch
    counts only when every element is a notification: a batch carrying a
    request must reach the SDK, which rejects batching outright at 2026-07-28.
    """
    if isinstance(decoded, list):
        return bool(decoded) and all(_is_notification(m) for m in decoded)
    return isinstance(decoded, dict) and "id" not in decoded


class AcceptClientNotifications:
    """Answer a client->server notification POST with 202 instead of 400.

    From protocol 2026-07-28 the SDK routes any request carrying an unknown
    `MCP-Protocol-Version` to its "modern" transport, which treats a body that
    is not a single JSON-RPC request object as one it cannot accept and answers
    400. A notification is exactly such a body, so a client that sends one --
    `notifications/roots/list_changed` is the common case, and Antigravity's
    first probe already tags requests `2026-07-28` -- gets a 400 back for a
    message it never asked to be answered.

    The 400 is what does the damage. Clients read an error status on a
    notification as the transport itself failing, not as one message being
    refused, and tear the whole connection down:

        MCP server connection closed unexpectedly for tuckit:
        sending "notifications/roots/list_changed": Bad Request

    So the user watches the tools appear and then quietly stop existing, which
    reads as a broken server rather than a refused message. This is the same
    shape as RefuseSseStream: one protocol surface we do not use, killing a
    transport that was working.

    202 is the streamable-http answer for a notification the server accepts,
    and accepting costs nothing here. This server registers no client
    notification handlers at all -- on the pre-2026 path the SDK logs "no
    handler for notification ..." and returns 202 itself -- so all this does is
    make the modern path behave the way every earlier one already did.

    `notifications/cancelled` is dropped along with the rest, which is correct
    for a stateless server: there is no session holding the in-flight request
    it would cancel. Anything genuinely worth acting on needs a handler first,
    and adding one means routing that method through instead of answering here.

    Ordering matches RefuseSseStream: this sits INSIDE the auth gate, so an
    unauthenticated POST still gets the 401 that carries OAuth discovery rather
    than a 202 that tells the client everything is fine.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        body, messages = await _drain(receive)
        try:
            decoded = json.loads(body)
        except ValueError:
            # Malformed JSON is the SDK's to answer -- it owns the parse-error
            # shape, and guessing at one here would diverge from it.
            decoded = None

        if decoded is not None and _is_notification(decoded):
            await send({"type": "http.response.start", "status": 202, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return

        await self.app(scope, _replay(messages), send)


async def _drain(receive):
    """Read the whole request body, keeping the raw messages for replay."""
    body = b""
    messages = []
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    return body, messages


def _replay(messages):
    """Hand the buffered messages back to the app, then keep it fed.

    The app must still be able to await after the buffer runs out -- a
    disconnect can arrive at any time -- so this falls through to a final
    http.disconnect rather than raising or hanging.
    """
    pending = list(messages)

    async def receive():
        if pending:
            return pending.pop(0)
        return {"type": "http.disconnect"}

    return receive


class ResetDatabaseConnections:
    """Give each MCP request Django's connection lifecycle, which it otherwise misses.

    Django closes a request's database connections when its own handler emits
    `request_started` / `request_finished`. The MCP app is a separate ASGI app
    mounted beside Django, so those signals never fire for it and nothing ever
    reaps what its queries opened.

    Every DB call under `/mcp` goes through `sync_to_async(..., thread_sensitive=True)`,
    which asgiref runs on one shared executor thread for the whole process. Django's
    connections are thread-local, so all of them accumulate on that single thread and
    live for as long as the process does. That is fine right up until something else
    closes the socket from the far end -- a serverless Postgres suspending on idle, a
    proxy reaping an idle connection, a failover. Django still holds the dead handle,
    hands it to the next query, and `/mcp` answers "the connection is closed" from
    then on, permanently, while the Django side of the very same process keeps
    working because its own requests open and close connections normally.

    This is what happened on 2026-08-20: the web app returned 200s throughout and
    every MCP tool call failed, until the process was replaced. It had been latent
    for a month, hidden by a keep-warm cron that pinged a DB-touching healthcheck
    every four minutes and so never let the database sleep. Removing that cron to
    measure real load is what exposed it.

    `close_old_connections()` closes anything unusable or past its age (CONN_MAX_AGE
    defaults to 0, so: everything), and the next query opens a fresh connection. It
    has to run through `sync_to_async(thread_sensitive=True)` for the same reason the
    bug exists -- it must land on the thread that owns the connections, not the event
    loop. Calling it directly from here would close nothing.

    Running it before AND after is deliberate. Before: repair a connection that died
    while the process sat idle, which is the case that bites. After: leave nothing
    open behind us, so a database that scales to zero actually can.

    Outermost in the stack on purpose -- outside the auth gate, because
    authenticating a bearer token is itself a query and would be the first thing to
    fail on a dead connection.

    Note for whoever greps the logs: "the connection is closed" is also the symptom
    RefuseSseStream describes, from an entirely different cause (a reaped SSE stream,
    client-side). Same words, different failure; this one is server-side and only
    ever follows a period of idleness.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await _close_old_connections()
        try:
            await self.app(scope, receive, send)
        finally:
            # finally, not "after a success": a request that raised is exactly
            # the one most likely to have left a broken connection behind.
            await _close_old_connections()
