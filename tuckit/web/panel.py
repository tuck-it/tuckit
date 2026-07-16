import markdown as md
import nh3

from tuckit.core.services.activity import slice_activity
from tuckit.core.services.bites import bite_progress, list_bites
from tuckit.core.services.plans import list_plans


def render_markdown_html(text: str) -> str:
    """Render untrusted markdown (human- or agent-written) to sanitized HTML."""
    return nh3.clean(md.markdown(text or "", extensions=["fenced_code"]))


# Back-compat alias (slice spec uses the same sanitizer).
render_spec_html = render_markdown_html


def slice_panel_context(slice_, is_panel: bool = False) -> dict:
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
    return {
        "slice": slice_,
        "spec_html": render_markdown_html(slice_.spec),
        "statuses": ["idea", "planned", "building", "shipped"],
        "activity": slice_activity(slice_),
        "is_panel": is_panel,
        "panel_qs": "?panel=1" if is_panel else "",
        "bites_done": done,
        "bites_total": total,
        "bites_pct": round(done / total * 100) if total else 0,
        "plans": plans,
    }
