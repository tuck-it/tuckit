import markdown as md
import nh3

from tuckit.core.services.activity import label_who, slice_activity
from tuckit.core.services.bites import bite_progress, list_bites
from tuckit.core.services.canvas import graph_for
from tuckit.core.services.orgs import policy_line_for
from tuckit.core.services.refs import slice_ref
from tuckit.core.services.slices import delegation_prompt, stage_of


# One list, every markdown surface. Slice specs, slice constraints and bite
# bodies all render through the function below, so an extension turned on here
# is on everywhere.
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


def slice_detail_context(slice_, is_modal: bool = False, viewer=None) -> dict:
    """Context for the ONE detail surface. There is no ticket panel and no plan
    card any more: the same template renders an unfiled capture and a filed
    slice, and `slice.area` is what decides how much of it appears.

    Everything the grown surface needs is computed unconditionally — an Inbox
    slice simply does not render it. Branching here as well would put the
    disclosure rule in two places, and they would drift.

    `viewer` is the OrgMember reading the page; it only decides whether an
    activity row says "you" or names someone. Omitting it shows addresses
    instead, which is safe: the row never claims a colleague's work was yours.
    """
    done, total = bite_progress(slice_)
    stage = stage_of(slice_)
    return {
        "slice": slice_,
        "stage": stage,
        # The one policy line that explains THIS slice's number. Not the whole
        # policy: that would repeat the same paragraph on every screen and bury
        # the line that applies.
        "policy_line": policy_line_for(slice_.org, slice_.priority),
        # The text a human copies to hand this slice to an agent. None once
        # there is no next step (shipped/dropped), which is half of the
        # template's gate; the other half is slice.area, because an unfiled
        # capture gets a perfectly good prompt that the panel deliberately
        # does not show.
        "delegation_prompt": delegation_prompt(slice_ref(slice_), slice_.title, stage),
        "spec_html": render_markdown_html(slice_.spec),
        # constraints is a first-class Slice field now (it used to hang off
        # Plan, which meant it was unreachable unless you first made a plan —
        # and almost nobody did).
        "constraints_html": render_markdown_html(slice_.constraints),
        # The canvas source is the decision record, always -- the spec has its
        # own block on this page and is not drawn here. Bodies go through the
        # same markdown surface as everything else -- there is deliberately no
        # second, narrower renderer for cards.
        # A written spec closes the record to new writes (propose_nodes and
        # choose_option both reject one), so a pick control on it could only
        # ever 400. Before TP-238 this state was unreachable because the record
        # was deleted at that point; keeping it is what made it possible.
        "canvas_closed": bool((slice_.spec or "").strip()),
        "canvas_nodes": [
            dict(node, body_html=render_markdown_html(node.get("body", "")))
            for node in graph_for(slice_)
        ],
        "bites": list(list_bites(slice_)),
        "activity": label_who(slice_activity(slice_), viewer),
        "is_modal": is_modal,
        # Appended to every mutation URL fired from inside the modal so the
        # re-render comes back as a card, not a full page.
        "modal_qs": "?modal=1" if is_modal else "",
        "bites_done": done,
        "bites_total": total,
        "bites_pct": round(done / total * 100) if total else 0,
    }
