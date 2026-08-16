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
