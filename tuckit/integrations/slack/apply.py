"""Map interpreted Slack intents onto tuckit's service layer.

Each intent from `interpret.py` is applied independently: writes go through
`tuckit.core.services.*` (never the ORM directly) so `assert_can_write` and
activity logging stay on the path, and a model-supplied ref is resolved with
`refs.parse_ref(org, ref)` — the only place a ref becomes a row. A hostile or
confused model that invents a ref cannot reach a primary key, and cannot
reach another org's board.
"""
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


def _create_slice(org, member, args) -> Applied:
    area = None
    if args.get("area"):
        area = Area.objects.filter(org=org, slug=args["area"]).first()
        # An area the model made up is not a reason to lose the capture: fall
        # back to the Inbox, which is where an unfiled slice belongs anyway.
    created = slice_services.create_slice(
        org, area=area, title=args["title"], spec=args.get("spec", ""),
        source="agent", member=member, created_by=member,
    )
    return Applied(ok=True, ref=slice_ref(created), label=created.title)


def _create_area(org, member, args) -> Applied:
    created = area_services.create_area(
        org, args["name"], args.get("description", ""),
        source="agent", member=member,
    )
    return Applied(ok=True, ref="", label=created.name)


def _add_note(org, member, args) -> Applied:
    # add_note lives in services.activity, not services.slices. Same function
    # the MCP add_note tool calls -- there is exactly one note path.
    target = _resolve_slice(org, args["ref"])
    activity_services.add_note(target, args["body"], source="agent", member=member)
    return Applied(ok=True, ref=slice_ref(target), label=target.title)


def _ask_clarification(org, member, args) -> Applied:
    # Not a failure of ours; the model chose to write nothing, which is the
    # correct outcome for a thread that is not slice-shaped.
    return Applied(ok=False, error=args.get("question", "What would you like me to file?"))


HANDLERS = {
    "create_slice": _create_slice,
    "create_area": _create_area,
    "add_note": _add_note,
    "ask_clarification": _ask_clarification,
}


def apply_intents(*, org, member, intents) -> list[Applied]:
    """Apply each intent independently and report what happened to each.

    Deliberately NOT wrapped in one transaction. If the third of three intents
    fails, undoing the two that worked is worse than saying which one did not.
    """
    results = []
    for intent in intents:
        handler = HANDLERS.get(intent.tool)
        if handler is None:
            results.append(Applied(ok=False, error=f"unknown action {intent.tool}"))
            continue
        try:
            results.append(handler(org, member, intent.args))
        except WritesBlocked as exc:
            # The deployment supplied this sentence; show it verbatim.
            results.append(Applied(ok=False, error=str(exc)))
        except (NotFound, InvalidValue, LimitReached) as exc:
            results.append(Applied(ok=False, error=str(exc)))
        except Exception as exc:
            logger.exception("slack intent %s failed", intent.tool)
            results.append(Applied(ok=False, error=f"unexpected error: {exc}"))
    return results
