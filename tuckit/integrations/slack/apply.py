"""Map interpreted Slack intents onto tuckit's service layer.

Each intent from `interpret.py` is applied independently: writes go through
`tuckit.core.services.*` (never the ORM directly) so `assert_can_write` and
activity logging stay on the path, and a model-supplied ref is resolved with
`refs.parse_ref(org, ref)` — the only place a ref becomes a row. A hostile or
confused model that invents a ref cannot reach a primary key, and cannot
reach another org's board.
"""
import hashlib
import json
import logging
from dataclasses import dataclass

from tuckit.core.models import Area, Slice
from tuckit.core.services import activity as activity_services
from tuckit.core.services import areas as area_services
from tuckit.core.services import slices as slice_services
from tuckit.core.services.exceptions import (
    InvalidValue, LimitReached, NotFound, WritesBlocked,
)
from tuckit.core.services.refs import parse_ref, slice_ref

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Applied:
    ok: bool
    ref: str = ""
    label: str = ""
    error: str = ""


def _content_fingerprint(intent) -> str:
    """A stable, per-process-independent fingerprint of what an intent DOES,
    not where it sits in the list.

    `interpret()` is a fresh model call on every retry, and nothing pins the
    order it returns intents in -- two create_slice intents can come back
    swapped. A positional key (index in the list) would then let a retry
    overwrite slice A with intent B's title/spec and vice versa: not a
    duplicate (the unique constraint still holds), but silently wrong
    content on two real rows, which is worse than the duplicate it would
    replace. Hashing the intent's own tool + args instead means intent B
    always carries B's key regardless of where a retry's response places it.

    json.dumps(..., sort_keys=True) rather than str(args): dict insertion
    order is not guaranteed to survive a re-serialization by the model
    across calls, and Python's hash() is salted per process (PYTHONHASHSEED)
    so it would not even reproduce within one process reliably -- hashlib is
    the only one of the three options that is actually stable.

    Two genuinely identical intents (same tool, same args) in one thread
    collide onto the same fingerprint, so the second overwrites the first
    rather than creating a second slice. That is treated as correct here:
    a model returning two identical create_slice calls for one mention is
    almost certainly repeating itself, not describing two real pieces of
    work, and collapsing them to one slice is the safer reading.
    """
    payload = json.dumps([intent.tool, intent.args], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _resolve_slice(org, ref: str) -> Slice:
    """A ref, never a primary key.

    parse_ref checks the org key prefix and raises NotFound, so an invented
    number cannot reach another org's board. This is the only place a ref is
    turned into a row; do not hand-parse one anywhere else.
    """
    number = parse_ref(org, ref)
    found = Slice.objects.filter(org=org, number=number).first()
    if found is None:
        raise NotFound(f"no slice {ref}")
    return found


def _create_slice(org, member, args, external_key: str = "") -> Applied:
    area = None
    if args.get("area"):
        area = Area.objects.filter(org=org, slug=args["area"]).first()
        # An area the model made up is not a reason to lose the capture: fall
        # back to the Inbox, which is where an unfiled slice belongs anyway.
    created = slice_services.create_slice(
        org, area=area, title=args["title"], spec=args.get("spec", ""),
        source="agent", member=member, created_by=member,
        external_key=external_key,
    )
    return Applied(ok=True, ref=slice_ref(created), label=created.title)


def _create_area(org, member, args, external_key: str = "") -> Applied:
    # NOTE: create_area has no external_key of its own, so a queue retry that
    # re-runs a successful create_area still creates a second area. Rarer
    # than the create_slice case (fewer intents per thread are create_area),
    # but real. Out of scope for this fix -- see bite-247-notes.txt.
    created = area_services.create_area(
        org, args["name"], args.get("description", ""),
        source="agent", member=member,
    )
    return Applied(ok=True, ref="", label=created.name)


def _add_note(org, member, args, external_key: str = "") -> Applied:
    # add_note lives in services.activity, not services.slices. Same function
    # the MCP add_note tool calls -- there is exactly one note path.
    # NOTE: add_note has no idempotency key either, so a queue retry that
    # re-runs a successful add_note appends a duplicate note. Lower stakes
    # than a duplicate slice (noise on a thread, not a duplicate board item)
    # so it is also out of scope here -- see bite-247-notes.txt.
    target = _resolve_slice(org, args["ref"])
    activity_services.add_note(target, args["body"], source="agent", member=member)
    return Applied(ok=True, ref=slice_ref(target), label=target.title)


def _ask_clarification(org, member, args, external_key: str = "") -> Applied:
    # Not a failure of ours; the model chose to write nothing, which is the
    # correct outcome for a thread that is not slice-shaped.
    return Applied(ok=False, error=args.get("question", "What would you like me to file?"))


HANDLERS = {
    "create_slice": _create_slice,
    "create_area": _create_area,
    "add_note": _add_note,
    "ask_clarification": _ask_clarification,
}


def apply_intents(*, org, member, intents, dedupe_key: str = "") -> list[Applied]:
    """Apply each intent independently and report what happened to each.

    Deliberately NOT wrapped in one transaction. If the third of three intents
    fails, undoing the two that worked is worse than saying which one did not.

    `dedupe_key` identifies the Slack message that produced `intents` (e.g.
    "slack:{channel}:{ts}") and defaults to "" so existing callers are
    unaffected. It exists because Cloud Tasks retries a failing job by
    calling handle_app_mention() again from the top -- a SECOND retry source
    on top of Slack's own retries, and one that never touches the SlackEvent
    row that dedupes those. If `apply_intents` already created some slices
    before a later step failed, a retry must not create them again. Per
    intent, `f"{dedupe_key}:{_content_fingerprint(intent)}"` becomes
    create_slice's `external_key`, which makes a repeat call update the same
    slice in place instead of duplicating it (see
    slice_services.create_slice's docstring). The key is keyed by the
    intent's own content, not its position in the list -- see
    _content_fingerprint's docstring for why a positional key is unsafe.
    Only create_slice gets this: it is the only handler whose repeat write
    is actually a duplicate board item, and it is the only one with an
    existing idempotency mechanism to reuse -- add_note and create_area are
    not covered, see the NOTE comments on their handlers.
    """
    results = []
    for intent in intents:
        handler = HANDLERS.get(intent.tool)
        if handler is None:
            results.append(Applied(ok=False, error=f"unknown action {intent.tool}"))
            continue
        external_key = f"{dedupe_key}:{_content_fingerprint(intent)}" if dedupe_key else ""
        try:
            results.append(handler(org, member, intent.args, external_key))
        except WritesBlocked as exc:
            # The deployment supplied this sentence; show it verbatim.
            results.append(Applied(ok=False, error=str(exc)))
        except (NotFound, InvalidValue, LimitReached) as exc:
            results.append(Applied(ok=False, error=str(exc)))
        except Exception as exc:
            logger.exception("slack intent %s failed", intent.tool)
            results.append(Applied(ok=False, error=f"unexpected error: {exc}"))
    return results
