"""Cmd+K server search — the half of "ref as shared vocabulary" that lets a
human act on a number an agent gave them."""

from django.shortcuts import render
from django.urls import reverse

from tuckit.core.models import Slice, Ticket
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.refs import parse_ref, ref_for
from tuckit.core.services.resolve import resolve_ref

_LIMIT = 8


def _row(org, obj, requested_ref=""):
    is_slice = isinstance(obj, Slice)
    ref = ref_for(obj)
    return {
        "ref": ref,
        "title": obj.title,
        "kind": "slice" if is_slice else "ticket",
        "url": reverse(
            "web:slice" if is_slice else "web:ticket", args=[org.slug, obj.pk]
        ),
        # Only set when the ref you typed is not the ref you landed on — i.e. an
        # absorbed ticket, whose work lives under another slice's number.
        "absorbed_from": requested_ref if requested_ref and requested_ref != ref else "",
    }


def _exact(org, q):
    """Resolve `q` as a ref, following promote/absorb links. Returns
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
        if obj is not None:
            results.append(_row(org, obj, requested_ref=requested))
            seen.add((type(obj).__name__, obj.pk))
        found = list(
            Slice.objects.filter(org=org, title__icontains=q).select_related("org")[:_LIMIT]
        ) + list(
            Ticket.objects.filter(org=org, title__icontains=q).select_related("org")[:_LIMIT]
        )
        for o in found:
            if (type(o).__name__, o.pk) not in seen:
                results.append(_row(org, o))
    return render(request, "web/partials/_cmdk_results.html", {"results": results, "q": q})
