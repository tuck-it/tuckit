from urllib.parse import urlparse

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.areas import create_area, list_areas, update_area, delete_area, reorder_area
from tuckit.core.services.slices import create_slice, inbox_slices
from tuckit.core.services.state import area_board_view
from tuckit.core.services.resolve import get_area, get_area_by_slug
from tuckit.core.services.tickets import slice_for_ticket
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import refresh_rollup, widget_oob
from tuckit.web.views._feedback import _action_result


def capture(request):
    """Capture always creates a Slice — Slice is the only unit of work now, so
    there is no Ticket to fork into. Area decides the destination directly:
    pick one and the slice files there immediately; leave it empty and the
    slice lands area-less in the Inbox (inbox_slices() in
    core/services/slices.py is what reads that back out).

    status/tags are not read here: they are not offered on this form, so a
    stale or hand-rolled POST carrying them is ignored rather than refused —
    create_slice's own defaults (status "open", no tags) apply.

    The note rides along as `spec` — the whole point of the Inbox is deciding,
    and you cannot decide on a bare title. The response is a bundle of
    out-of-band swaps (toast, live count) so one response works from any page;
    htmx drops OOB targets that are not on screen."""
    org = get_current_org(request)

    title = request.POST.get("title", "").strip()
    if not title:
        return HttpResponse("Title is required", status=400)

    area = None
    if request.POST.get("area_id"):
        try:
            area = get_area(org, int(request.POST["area_id"]))
        except (NotFound, ValueError):
            raise Http404

    create_slice(org, area=area, title=title, spec=request.POST.get("spec", "").strip(),
                 source="human")
    return _action_result(request, org,
                          f"Captured in {area.name}." if area else "Captured to Inbox.")


def inbox(request):
    """The Inbox: area-less open Slices, newest first (inbox_slices() in
    core/services/slices.py is the single predicate for "is this unfiled").
    Triage is picking an Area on the row — reversible, since clearing it
    (set_slice_area(slice_, None)) sends the slice right back here. There is
    no dismiss/duplicate review surface any more: those were Ticket-only
    concepts and a Slice has nothing equivalent to review."""
    org = get_current_org(request)
    return render(request, "web/inbox.html", {
        "slices": list(inbox_slices(org)),
        "areas": list(list_areas(org)),
    })


def ticket_detail(request, ticket_id):
    """A Ticket has no surface of its own any more — this route only forwards
    to the Slice that capture became (slice_for_ticket()).

    It used to return the triage modal, whose Promote was the one action in
    the product that could not be undone. Deleting the modal without deleting
    the endpoint would have left that action reachable by a hand-made POST, so
    ticket_edit/dismiss/reopen/triage/release went with it.

    HX-Redirect rather than a bare 302 for htmx callers: an htmx GET follows a
    redirect transparently, which would splice a whole page into the overlay
    that asked for a card. The header makes the browser navigate instead — and
    a full navigation is also what lets a queued message reach the next page."""
    org = get_current_org(request)
    slice_ = slice_for_ticket(org, ticket_id)
    if slice_ is None:
        # A Ticket that 0045 never folded — i.e. one an agent created after
        # this release through the (still live) create_ticket MCP tool. 404ing
        # would park the loading skeleton in the overlay with no explanation,
        # and the Area strip + Cmd+K both still link here. Send the reader to
        # the Inbox and say why.
        messages.info(request, "That capture has no slice — showing the Inbox instead.")
        url = reverse("web:inbox", args=[org.slug])
    else:
        url = reverse("web:slice", args=[org.slug, slice_.id])
    if request.headers.get("HX-Request"):
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = url
        return resp
    return redirect(url)


def area_create(request):
    org = get_current_org(request)
    create_area(org, request.POST["name"], description=request.POST.get("description", ""), source="human")
    # OOB-swap the sidebar Areas list instead of a full-page reload; the
    # sidebar_areas context processor supplies the refreshed `areas`. Also
    # OOB-refresh the onboarding widget so its Step-1 checkbox ticks live.
    html = render_to_string("web/partials/_area_nav.html", {"oob": True}, request=request)
    return refresh_rollup(request, HttpResponse(html + widget_oob(request)))


def area_rename(request, area_id):
    org = get_current_org(request)
    try:
        area = get_area(org, area_id)
    except NotFound:
        raise Http404
    try:
        update_area(area, name=request.POST.get("name", ""))
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    # If the user is renaming the area they're currently viewing, keep its
    # sidebar highlight: the swapped-in row is rendered under url_name
    # 'area_rename', so resolver_match can't infer active — derive it from the
    # browser's current URL (htmx sends it as HX-Current-URL).
    current_path = urlparse(request.headers.get("HX-Current-URL", "")).path
    active = current_path == reverse("web:area", args=[org.slug, area.slug])
    # Re-read with the slice_count annotation the row's delete confirmation
    # needs; `area` above came back from update_area() unannotated, which would
    # render "and its  slices" with the number silently missing.
    area = list_areas(org).annotate(
        slice_count=Count("slices", filter=~Q(slices__status="dropped"))
    ).get(pk=area.pk)
    return render(request, "web/partials/_area_row.html", {"a": area, "active": active})


def area_edit(request, area_id):
    org = get_current_org(request)
    try:
        area = get_area(org, area_id)
    except NotFound:
        raise Http404
    try:
        update_area(
            area,
            name=request.POST.get("name", ""),
            description=request.POST.get("description", ""),
        )
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    html = render_to_string("web/partials/_area_header.html", {"area": area}, request=request)
    nav = render_to_string("web/partials/_area_nav.html", {"oob": True}, request=request)
    return HttpResponse(html + nav)


def area_delete(request, area_id):
    org = get_current_org(request)
    try:
        area = get_area(org, area_id)
    except NotFound:
        raise Http404
    try:
        delete_area(area)
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return HttpResponse(status=204)  # htmx empties the row via hx-swap="outerHTML"


def area_move(request, area_id):
    """Move an Area one place up or down in the sidebar.

    The pointer/keyboard equivalent of dragging the row. Reordering was
    drag-only, which fails WCAG 2.5.7 (Dragging Movements) — SortableJS has no
    keyboard affordance and the row menu offered only Rename/Delete. Neighbours
    are resolved on the server so the caller just says "up" or "down".
    """
    org = get_current_org(request)
    try:
        area = get_area(org, area_id)
    except NotFound:
        raise Http404
    direction = request.POST.get("direction")
    if direction not in ("up", "down"):
        return HttpResponse("Direction must be 'up' or 'down'.", status=400)

    siblings = list(list_areas(org))
    try:
        i = next(n for n, a in enumerate(siblings) if a.id == area.id)
    except StopIteration:
        raise Http404
    # rank_for() prefers `after` and ignores `before` when both are given, so
    # pass exactly one: it finds the real neighbour on the other side itself.
    if direction == "up":
        if i == 0:
            return HttpResponse("That area is already first.", status=400)
        reorder_area(area, before=siblings[i - 1])
    else:
        if i == len(siblings) - 1:
            return HttpResponse("That area is already last.", status=400)
        reorder_area(area, after=siblings[i + 1])
    # `areas` comes from the sidebar_areas context processor (already annotated
    # with slice_count for the delete confirmation), so the re-rendered nav is
    # identical to a fresh page load's.
    return render(request, "web/partials/_area_nav.html", {})


def area_reorder(request, area_id):
    org = get_current_org(request)
    try:
        area = get_area(org, area_id)
        before = get_area(org, int(request.POST["before_id"])) if request.POST.get("before_id") else None
        after = get_area(org, int(request.POST["after_id"])) if request.POST.get("after_id") else None
    except NotFound:
        raise Http404
    reorder_area(area, before=before, after=after)
    return HttpResponse(status=204)


def area_slice_create(request, slug):
    org = get_current_org(request)
    try:
        area = get_area_by_slug(org, slug)
    except NotFound:
        raise Http404
    title = request.POST.get("title", "").strip()
    if title:
        target = area
        if request.POST.get("area_id"):
            try:
                target = get_area(org, int(request.POST["area_id"]))
            except (NotFound, ValueError):
                raise Http404
        # No status field on the form any more — a new slice always starts
        # "open"; Ship/Drop are the only way to change it (create_slice's
        # default already is "open").
        spec = request.POST.get("spec", "").strip()
        tags = [t.strip() for t in request.POST.getlist("tags") if t.strip()]
        try:
            create_slice(org, area=target, title=title, spec=spec, tags=tags, source="human")
        except InvalidValue as e:
            return HttpResponse(str(e), status=400)
    board = area_board_view(area)
    html = render_to_string("web/partials/_board.html", {
        "area": area,
        "groups": board["groups"],
        "shipped_total": board["shipped_total"],
        "shipped_hidden": board["shipped_hidden"],
    }, request=request)
    return refresh_rollup(request, HttpResponse(html + widget_oob(request)))
