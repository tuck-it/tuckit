import markdown as md
import nh3

from tuckit.core.services.activity import slice_activity
from tuckit.core.services.bites import bite_progress, list_bites
from tuckit.core.services.plans import list_plans
from tuckit.core.services.slices import stage_of
from tuckit.core.services.tickets import origin_ticket


# One list, every markdown surface. Slice specs, ticket bodies, plan
# overview/constraints and bite bodies all render through the function below,
# so an extension turned on here is on everywhere.
#   tables     — pipe tables. Agents write these constantly; without the
#                extension they rendered as a paragraph of pipes.
#   sane_lists — a "-" list directly after a "1." list must not be swallowed
#                into it as item 2.
_MD_EXTENSIONS = ["fenced_code", "tables", "sane_lists"]


def render_markdown_html(text: str) -> str:
    """Render untrusted markdown (human- or agent-written) to sanitized HTML."""
    return nh3.clean(md.markdown(text or "", extensions=_MD_EXTENSIONS))


# Back-compat alias (slice spec uses the same sanitizer).
render_spec_html = render_markdown_html


def slice_detail_context(slice_, is_modal: bool = False) -> dict:
    done, total = bite_progress(slice_)
    plans = [
        {
            "plan": plan,
            "plan_html": render_markdown_html(plan.body) if plan.body else "",
            "constraints_html": render_markdown_html(plan.constraints) if plan.constraints else "",
            "bites": list(list_bites(plan)),
        }
        for plan in list_plans(slice_)
    ]
    # Slice -> ticket, the mirror of the link the ticket modal already renders
    # the other way. Since promote stopped copying the body into spec, this is
    # how the original capture stays reachable from here.
    linked = list(slice_.tickets.all())
    origin = origin_ticket(slice_)
    return {
        "slice": slice_,
        "stage": stage_of(slice_),
        "origin_ticket": origin,
        "absorbed_tickets": [t for t in linked if t != origin],
        "spec_html": render_markdown_html(slice_.spec),
        "activity": slice_activity(slice_),
        "is_modal": is_modal,
        # Appended to every mutation URL fired from inside the modal so the
        # re-render comes back as a card, not a full page.
        "modal_qs": "?modal=1" if is_modal else "",
        "bites_done": done,
        "bites_total": total,
        "bites_pct": round(done / total * 100) if total else 0,
        "plans": plans,
    }
