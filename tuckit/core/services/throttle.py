"""Policy on top of the token bucket: where the numbers come from, what the key
is, and what happens when a bucket refuses.

services/ratelimit.py is the mechanism and stays Django-free. This is the layer
that knows about settings, connections, orgs and logging.
"""
import logging
import time

from django.conf import settings

from tuckit.core.models import ThrottleEpisode
from tuckit.core.services import ratelimit
from tuckit.core.services.exceptions import LimitReached

log = logging.getLogger(__name__)

EPISODE_SUPPRESS_SECONDS = 300

# bucket key -> monotonic time of the last row written for it.
_last_recorded: dict = {}

# The agent reads this and nothing else, so it has to change the agent's
# behaviour. Retry guidance on its own makes a runaway loop retry faster; the
# last sentence is the one that matters.
TOO_FAST = (
    "rate limit: this agent connection is making too many MCP calls. "
    "Wait 30s and retry. If you are in a loop, stop and report instead of retrying."
)


def _record_episode(conn, *, now: float | None = None) -> None:
    """Write one ThrottleEpisode, unless one was written for this key recently.

    The suppression is what keeps the defence from becoming the load: without
    it, a connection refused ten times a second would write ten rows a second
    to the database this whole slice exists to protect.
    """
    now = time.monotonic() if now is None else now
    last = _last_recorded.get(conn.key)
    if last is not None and now - last < EPISODE_SUPPRESS_SECONDS:
        return
    _last_recorded[conn.key] = now
    ThrottleEpisode.objects.create(org=conn.org, label=conn.label)


def reset() -> None:
    """Tests only: the suppression map is module-level and outlives a test."""
    _last_recorded.clear()


def check(conn) -> None:
    """Spend one token for this connection and one for its org.

    Raises LimitReached if either refuses. The connection layer is checked
    first because it is the one that identifies a single broken agent; the org
    layer is a bound rather than a budget and a real team never reaches it.
    """
    conn_per_sec = float(getattr(settings, "TUCKIT_MCP_RATE_CONN_PER_SEC", 0) or 0)
    if conn_per_sec > 0 and not ratelimit.allow(
        conn.key,
        burst=float(settings.TUCKIT_MCP_RATE_CONN_BURST),
        per_sec=conn_per_sec,
    ):
        _record_episode(conn)
        raise LimitReached(TOO_FAST)

    org_per_sec = float(getattr(settings, "TUCKIT_MCP_RATE_ORG_PER_SEC", 0) or 0)
    if org_per_sec > 0 and not ratelimit.allow(
        ("org", conn.org.id),
        burst=float(settings.TUCKIT_MCP_RATE_ORG_BURST),
        per_sec=org_per_sec,
    ):
        # No database row for this one. An org-wide refusal is an incident, not
        # a customer-support fact, and incidents belong in logs and alerts.
        log.warning("mcp org rate limit hit: org=%s", conn.org.slug)
        raise LimitReached(TOO_FAST)
