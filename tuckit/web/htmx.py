from urllib.parse import urlparse

from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import resolve, reverse
from django.urls.exceptions import Resolver404

# Pages whose body is a computed roll-up (counts, status columns, stat cards)
# rather than a list we OOB-swap. A mutation elsewhere leaves them showing
# yesterday's numbers, so they get a real refresh instead.
_ROLLUP_VIEWS = {"home", "roadmap", "areas", "area"}


def refresh_rollup(request, response):
    """Ask htmx to reload the page when the user is standing on a roll-up view.

    Creating the first slice from Home used to leave the dashboard reading
    "Backlog 0 / No planned work queued" while the onboarding widget ticked
    "Add your first Slice" — the OOB swaps covered the sidebar and the widget
    but not the numbers, so the page contradicted itself. Rather than OOB-swap
    every derived figure on every page, refresh the ones that are entirely
    derived. Mutations made from a list page (Inbox, slice panel) are unaffected:
    those already swap the thing that changed.
    """
    current = request.headers.get("HX-Current-URL")
    if not current:
        return response
    try:
        match = resolve(urlparse(current).path)
    except Resolver404:
        return response
    if match.url_name in _ROLLUP_VIEWS:
        response["HX-Refresh"] = "true"
    return response


def widget_oob(request) -> str:
    """Render the onboarding widget as an OOB fragment (empty string when the
    widget is hidden, so callers can safely concatenate it onto any HTMX
    response). Context processors supply the onboarding state; oob=True adds the
    hx-swap-oob marker so HTMX re-renders the widget in place — this is how a
    panel or capture mutation ticks an onboarding step without a full reload."""
    return render_to_string("web/partials/_onboarding_widget.html", {"oob": True}, request=request)


def redirect_response(request, url_name: str, **kwargs):
    """Redirect to ``url_name`` (with optional reverse kwargs), doing the right thing for
    hx-post forms.

    HTMX turns an ordinary 302 into an in-place content swap (it follows the
    redirect and injects the target page into the triggering element). For a
    form that should navigate the whole browser — e.g. a destructive delete —
    emit an ``HX-Redirect`` header so HTMX performs a full navigation instead.
    Non-HTMX requests still get a plain 302.
    """
    if request.headers.get("HX-Request"):
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = reverse(url_name, kwargs=kwargs)
        return resp
    return redirect(url_name, **kwargs)
