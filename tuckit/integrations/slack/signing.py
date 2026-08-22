import hashlib
import hmac
import time

# Slack's own recommendation. Anything older is a replay, not a slow network.
MAX_SKEW_SECONDS = 60 * 5


class SlackSignatureError(Exception):
    """The request did not come from Slack, or came too long ago."""


def verify_signature(*, signing_secret: str, timestamp: str, raw_body: bytes,
                     signature: str, now: float | None = None) -> None:
    """Raise unless this is a fresh, genuinely Slack-signed request.

    `raw_body` must be the bytes exactly as they arrived. Anything that has
    already parsed and re-serialised the body produces a different digest, so
    the caller reads request.body before touching request.POST.
    """
    now = time.time() if now is None else now
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        raise SlackSignatureError("missing or malformed timestamp")
    if abs(now - sent_at) > MAX_SKEW_SECONDS:
        raise SlackSignatureError("timestamp outside the replay window")
    # The timestamp goes into the basestring as the string Slack sent, not a
    # reparsed int: normalising it would change the digest.
    base = b"v0:" + timestamp.encode() + b":" + raw_body
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise SlackSignatureError("signature mismatch")
