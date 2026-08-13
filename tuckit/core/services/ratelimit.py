"""A token bucket, and nothing else.

Deliberately Django-free: this takes a key, two numbers and a clock, and
answers one question. Settings, key construction, episode recording and
logging live one layer up in services/throttle.py, which is what lets this be
unit-tested at exact timestamps with no database and no settings.

Burst and rate are separate on purpose. Legitimate agent load is bursty (a
delegating run fans out subagents and hundreds of calls land in seconds); a
runaway loop is sustained. A plain "N per minute" window cannot tell those
apart. A token bucket is generous to the first and hostile to the second.
"""
import time

# key -> (tokens, updated_at, full_after). `full_after` is how many seconds a
# fully drained bucket needs to refill; it is stored per entry because the two
# layers (per connection, per org) have different numbers and must be swept
# independently.
_buckets: dict = {}

_calls = 0
_SWEEP_EVERY = 1000


def allow(key, *, burst: float, per_sec: float, now: float | None = None) -> bool:
    """Spend one token for `key`. True if one was available.

    Refill is lazy. There is no background timer and no periodic task: each
    call credits the time that has actually passed since it last looked. That
    is the only arithmetic in this module and the only place it can be wrong.

    No lock is taken. The only caller is reached through Django's
    `sync_to_async(..., thread_sensitive=True)`, which serialises all such work
    onto a single executor thread, so two calls can never interleave here
    either.

    `per_sec` must be > 0. A zero rate means the caller has switched that layer
    off and should not have called at all; passing it here would drain the
    bucket once and then block forever.
    """
    global _calls
    now = time.monotonic() if now is None else now
    full_after = burst / per_sec

    _calls += 1
    if _calls % _SWEEP_EVERY == 0:
        _sweep(now)

    tokens, updated, _ = _buckets.get(key, (burst, now, full_after))
    tokens = min(burst, tokens + (now - updated) * per_sec)
    if tokens < 1:
        _buckets[key] = (tokens, now, full_after)
        return False
    _buckets[key] = (tokens - 1, now, full_after)
    return True


def _sweep(now: float) -> None:
    """Drop every bucket that must be full by now.

    A missing key starts full, so a full bucket and an absent one are the same
    state and discarding one loses nothing. This is why there is no LRU and no
    maximum size: the keys that must not be dropped are the ones being
    hammered, and those are never idle.

    Run inline off a call counter rather than on a timer, so an idle server
    does no work at all.
    """
    stale = [
        key for key, (_tokens, updated, full_after) in _buckets.items()
        if now - updated >= full_after
    ]
    for key in stale:
        del _buckets[key]


def reset() -> None:
    """Drop all state. Tests must call this: the dict is module-level and
    outlives a single test, so without it tests pass alone and fail in suite
    order."""
    global _calls
    _buckets.clear()
    _calls = 0
