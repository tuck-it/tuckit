"""Policy on top of the token bucket: where the numbers come from, what the key
is, and what happens when a bucket refuses.

services/ratelimit.py is the mechanism and stays Django-free. This is the layer
that knows about settings, connections, orgs and logging.
"""
import logging

from django.conf import settings

from tuckit.core.services import ratelimit
from tuckit.core.services.exceptions import LimitReached

log = logging.getLogger(__name__)

# The agent reads this and nothing else, so it has to change the agent's
# behaviour. Retry guidance on its own makes a runaway loop retry faster; the
# last sentence is the one that matters.
TOO_FAST = (
    "rate limit: this agent connection is making too many MCP calls. "
    "Wait 30s and retry. If you are in a loop, stop and report instead of retrying."
)


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
