from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse


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
