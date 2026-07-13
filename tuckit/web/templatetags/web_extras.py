from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

from tuckit.core.services import bites as bites_svc
from tuckit.web.panel import render_markdown_html

register = template.Library()


@register.simple_tag(name="wurl", takes_context=True)
def wurl_tag(context, name, *args, **kwargs):
    """Reverse a workspace-scoped route for the current org/workspace. Fills the
    <org_slug>/<ws_slug> prefix from `current_workspace` so app templates don't repeat it."""
    ws = context.get("current_workspace")
    if ws is None:
        return "#"
    return reverse(name, args=[ws.org.slug, ws.slug, *args], kwargs=kwargs)


@register.simple_tag(name="bite_progress")
def bite_progress_tag(slice):
    done, total = bites_svc.bite_progress(slice)
    return f"{done}/{total}" if total else ""


_ICON_PATHS = {
    "home": '<path d="M3 9.5 12 3l9 6.5"/><path d="M5 10v10h14V10"/>',
    "triage": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.5 2 12v7h20v-7l-3.5-6.5H5.5Z"/>',
    "attention": '<path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
    "in-progress": '<path d="M3 12h4l2 6 4-14 2 8h6"/>',
    "roadmap": '<path d="M4 6h4v13H4zM10 3h4v16h-4zM16 9h4v10h-4z"/>',
    "area": '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "settings": '<path d="M4 7h11M19 7h1M4 12h1M9 12h11M4 17h7M15 17h5"/><circle cx="17" cy="7" r="2"/><circle cx="7" cy="12" r="2"/><circle cx="13" cy="17" r="2"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "note": '<path d="M4 5h16M4 10h16M4 15h10"/>',
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "check": '<path d="m5 12 4 4 9-10"/>',
    "activity": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
}


@register.simple_tag
def attention_label(item):
    days = item.get("days", 0)
    if item.get("reason") == "triage_stale":
        return f"Triage {days}d"
    return f"{days}d idle"


@register.simple_tag
def icon(name, cls="icon"):
    paths = _ICON_PATHS.get(name, "")
    return mark_safe(
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )


@register.simple_tag
def render_bite_body(bite):
    return mark_safe(render_markdown_html(bite.body))
