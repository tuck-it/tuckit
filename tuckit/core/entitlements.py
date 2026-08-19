from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string

from tuckit.core.services.exceptions import LimitReached, WritesBlocked


@dataclass(frozen=True)
class Entitlements:
    seat_limit: int | None = None  # None = unlimited

    # Empty string = writes allowed. A non-empty value is the sentence shown to
    # whoever tried to write, and core never learns why it was set: a deployment
    # that closes writes supplies its own wording through the hook. Keeping the
    # reason here rather than a boolean is what stops product vocabulary —
    # plans, prices, trials — from leaking into the source-available core.
    writes_blocked_reason: str = ""


_UNLIMITED = Entitlements()


def resolve_entitlements(org) -> Entitlements:
    """Return the org's limits. No hook configured (self-host) → everything unlimited."""
    path = getattr(settings, "TUCKIT_ENTITLEMENTS_HOOK", None)
    if not path:
        return _UNLIMITED
    return import_string(path)(org)


def assert_can_write(org) -> None:
    """Refuse a write, with the reason, when the deployment has closed writes.

    Called from the write services rather than from each MCP tool or view, so
    that both surfaces are covered by one gate and a new caller cannot forget
    it. Reads are never routed through here — the whole point is that a blocked
    org still sees everything it has.
    """
    reason = resolve_entitlements(org).writes_blocked_reason
    if reason:
        raise WritesBlocked(reason)


def assert_can_add_seat(org) -> None:
    ent = resolve_entitlements(org)
    if ent.seat_limit is None:
        return
    # Lazy imports avoid an import cycle (invitations -> entitlements -> orgs/models).
    from tuckit.core.models import Invitation
    from tuckit.core.services.orgs import seat_count

    pending = Invitation.objects.filter(org=org, accepted_at__isnull=True).count()
    if seat_count(org) + pending >= ent.seat_limit:
        raise LimitReached(f"seat limit reached ({ent.seat_limit})")
