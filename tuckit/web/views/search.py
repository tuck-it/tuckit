"""Cmd+K server search — the half of "ref as shared vocabulary" that lets a
human act on a number an agent gave them.

Slices only. This module used to query Ticket alongside Slice and mark the
resolved ones with a Promoted/Dismissed/Duplicate badge, because promote copied
the ticket's title AND its number onto the new slice and the ticket row lived
on. 0045 folds every ticket into a slice with that same identical title and
identical ref, so keeping the Ticket branch meant the product's primary lookup
surface answered every one of the ~52 production captures with two rows bearing
the same ref. There is one unit of work now, so there is one kind of result.
"""

from django.shortcuts import render
from django.urls import reverse

from tuckit.core.models import Slice
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.refs import parse_ref, ref_for
from tuckit.core.services.resolve import resolve_ref

_LIMIT = 8


def _row(org, obj, requested_ref=""):
    ref = ref_for(obj)
    return {
        "ref": ref,
        "title": obj.title,
        "kind": "slice",
        "url": reverse("web:slice", args=[org.slug, obj.pk]),
        # Only set when the ref you typed is not the ref you landed on — i.e. an
        # absorbed capture, whose work lives under another slice's number.
        "absorbed_from": requested_ref if requested_ref and requested_ref != ref else "",
    }


def _exact(org, q):
    """Resolve `q` as a ref, following absorb links. Returns
    (obj, requested_ref) or (None, "")."""
    # A bare number is a ref on this surface, not a primary key: the palette is
    # where a human types what they read off the screen. MCP's
    # get_slice_flexible() still reads bare digits as ids; that asymmetry is
    # deliberate and left alone.
    ref = f"{org.key}-{q}" if q.isdigit() else q
    try:
        parse_ref(org, ref)
        return resolve_ref(org, ref), ref.upper()
    except NotFound:
        return None, ""


def search(request):
    org = request.org
    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        obj, requested = _exact(org, q)
        seen = set()
        # resolve_ref() still knows about Tickets until 0047 drops the table: a
        # ref that 0045 could not fold resolves to a Ticket, which has no page
        # to link to. The palette shows slices, so drop it rather than emit a
        # row whose href would 404.
        if isinstance(obj, Slice):
            results.append(_row(org, obj, requested_ref=requested))
            seen.add(obj.pk)
        for o in Slice.objects.filter(org=org, title__icontains=q).select_related("org")[:_LIMIT]:
            if o.pk not in seen:
                results.append(_row(org, o))
    return render(request, "web/partials/_cmdk_results.html", {"results": results, "q": q})
