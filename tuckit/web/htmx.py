from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse


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
