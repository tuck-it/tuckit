from django import template
from django.utils.safestring import mark_safe

from tuckit.core.services import bites as bites_svc
from tuckit.web.panel import render_markdown_html

register = template.Library()


@register.simple_tag(name="bite_progress")
def bite_progress_tag(slice):
    done, total = bites_svc.bite_progress(slice)
    return f"{done}/{total}" if total else ""


_ICON_PATHS = {
    "home": '<path d="M3 9.5 12 3l9 6.5"/><path d="M5 10v10h14V10"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.5 2 12v7h20v-7l-3.5-6.5H5.5Z"/>',
    "area": '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "settings": '<path d="M4 7h11M19 7h1M4 12h1M9 12h11M4 17h7M15 17h5"/><circle cx="17" cy="7" r="2"/><circle cx="7" cy="12" r="2"/><circle cx="13" cy="17" r="2"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "note": '<path d="M4 5h16M4 10h16M4 15h10"/>',
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "check": '<path d="m5 12 4 4 9-10"/>',
}


@register.simple_tag
def attention_label(item):
    days = item.get("days", 0)
    if item.get("reason") == "inbox_stale":
        return f"인박스 {days}일째"
    return f"{days}일째 진척 없음"


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
