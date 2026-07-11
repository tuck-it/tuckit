import markdown as md
import nh3

from tuckit.core.services.bites import list_bites


def render_markdown_html(text: str) -> str:
    """Render untrusted markdown (human- or agent-written) to sanitized HTML."""
    return nh3.clean(md.markdown(text or "", extensions=["fenced_code"]))


# Back-compat alias (slice spec uses the same sanitizer).
render_spec_html = render_markdown_html


def slice_panel_context(slice_) -> dict:
    return {
        "slice": slice_,
        "spec_html": render_markdown_html(slice_.spec),
        "bites": list(list_bites(slice_)),
        "statuses": ["idea", "planned", "building", "shipped"],
    }
