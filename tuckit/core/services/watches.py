"""The capability channel behind a canvas click.

An agent designing a slice waits for a human to pick an option in their
browser. It cannot wait on tuckit directly: the loop that does the waiting is a
shell command, and giving a shell command tuckit credentials is exactly what
this design refuses to do. So `propose` hands back an opaque URL that answers
one question and expires on its own.
"""
import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from tuckit.core.models import CanvasWatch

# A question nobody has answered in fifteen minutes is not waiting on a
# browser any more, it is waiting on a conversation -- and an abandoned URL
# should stop being a live channel quickly. The skill's poll loop is sized
# against this number, so moving it means moving that too.
WATCH_TTL = timedelta(minutes=15)
# Once answered it only has to survive the poll that reads it, plus a retry.
# Killing it on the read instead would strand an agent whose one request failed.
ANSWER_GRACE = timedelta(minutes=5)


def hash_watch_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def open_watch(slice_):
    """Issue a watch on one slice. Returns (watch, raw token).

    The raw token is returned once and never stored. Opening also sweeps the
    org's dead watches, so this needs no cron: the write path pays for its own
    cleanup, and the volume is one row per design question.
    """
    now = timezone.now()
    CanvasWatch.objects.filter(org=slice_.org, expires_at__lt=now).delete()
    raw = secrets.token_urlsafe(32)
    watch = CanvasWatch.objects.create(
        org=slice_.org, slice=slice_, token_hash=hash_watch_token(raw),
        expires_at=now + WATCH_TTL,
    )
    return watch, raw


def read_watch(raw: str) -> dict | None:
    """What the capability URL answers. None when nothing alive matches.

    Deliberately one indexed lookup and nothing else. This runs
    unauthenticated, so it must not become a way to ask questions about a
    slice: no title, no spec, no node body -- only the id the agent wrote.
    """
    watch = CanvasWatch.objects.filter(
        token_hash=hash_watch_token(raw), expires_at__gt=timezone.now()
    ).first()
    if watch is None:
        return None
    if watch.choice:
        return {"status": "chosen", "choice": watch.choice}
    return {"status": "waiting"}


def answer_watches(slice_, node_id: str) -> int:
    """Tell this slice's live, unanswered watches which node was picked.

    Only unanswered ones: an answered watch has been read, or is about to be,
    and rewriting it would change an answer someone may already have acted on.
    The expiry is set to the grace window rather than clamped so a nearly-dead
    watch can still deliver the thing it was waiting for.
    """
    now = timezone.now()
    return CanvasWatch.objects.filter(
        slice=slice_, choice="", expires_at__gt=now
    ).update(choice=node_id, expires_at=now + ANSWER_GRACE)


def close_watches(slice_) -> int:
    """Retire every watch on a slice -- the design stopped being open."""
    return CanvasWatch.objects.filter(slice=slice_).delete()[0]
