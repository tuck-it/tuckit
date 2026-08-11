"""Cmd+K server search — the half of "ref as shared vocabulary" that lets a
human act on a number an agent gave them.

Slices only. This module used to query Ticket alongside Slice and mark the
resolved ones with a Promoted/Dismissed/Duplicate badge, because promote copied
the ticket's title AND its number onto the new slice and the ticket row lived
on. 0045 folded every ticket into a slice with that same identical title and
identical ref, and 0050 dropped the table outright. There is one unit of work
now, so there is one kind of result.
"""

from django.shortcuts import render
from django.urls import reverse

from tuckit.core.models import Slice
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.refs import ref_for
from tuckit.core.services.resolve import get_slice_by_ref

_LIMIT = 8


def _row(org, obj):
    return {
        "ref": ref_for(obj),
        "title": obj.title,
        "kind": "slice",
        "url": reverse("web:slice", args=[org.slug, obj.pk]),
    }


def _exact(org, q):
    """The Slice `q` names as a ref, or None.

    A bare number is a ref on this surface, not a primary key: the palette is
    where a human types what they read off the screen. MCP's
    get_slice_flexible() still reads bare digits as ids; that asymmetry is
    deliberate and left alone.

    No absorb-following left to do. That existed because an absorbed Ticket
    kept its own number while its work moved under another Slice's ref, so the
    ref you typed was not the ref you landed on. 0050 dropped the Ticket table,
    and a Slice number resolves only ever to itself."""
    ref = f"{org.key}-{q}" if q.isdigit() else q
    try:
        return get_slice_by_ref(org, ref)
    except NotFound:
        return None


def search(request):
    org = request.org
    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        obj = _exact(org, q)
        seen = set()
        if obj is not None:
            results.append(_row(org, obj))
            seen.add(obj.pk)
        for o in Slice.objects.filter(org=org, title__icontains=q).select_related("org")[:_LIMIT]:
            if o.pk not in seen:
                results.append(_row(org, o))
    return render(request, "web/partials/_cmdk_results.html", {"results": results, "q": q})
