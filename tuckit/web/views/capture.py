from urllib.parse import urlparse

from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.areas import create_area, list_areas, update_area, delete_area, reorder_area
from tuckit.core.services.slices import create_slice, set_slice_status
from tuckit.core.services.state import area_board_view
from tuckit.core.services.tickets import (
    create_ticket, query_tickets, ticket_queryset, promote_ticket, reopen_ticket,
    resolve_ticket, update_ticket,
)
from tuckit.web.detail import render_markdown_html
from tuckit.core.services.resolve import get_area, get_ticket, get_area_by_slug, get_slice
from tuckit.core.services.slices import query_slices
from tuckit.core.services.tickets import absorb_ticket, origin_ticket, release_ticket
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import refresh_rollup, widget_oob

_SLICE_STATUSES = ["planned", "building", "shipped"]


def capture(request):
    """Capture always creates a Ticket.

    Area answers "which part of the product", not "are we doing this" — two
    different axes. So picking one files the ticket without committing to it:
    the ticket stays `open` in the Inbox either way. The Area select used to BE
    the Ticket/Slice fork, which meant an idea you had already filed became a
    `planned` Slice the moment you said where it belonged, and there was no way
    to just park it.

    status/tags are not read here. A Ticket has neither, so the form no longer
    offers them; a stale or hand-rolled POST carrying them is ignored rather
    than refused — there is nowhere to put them, but that is no reason to throw
    the capture away. Slices are authored from an Area's "+ New slice" or by
    promoting a ticket."""
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

    # The note rides along in `body` — the whole point of the Inbox is deciding,
    # and you cannot decide on a bare title. The response is a bundle of
    # out-of-band swaps (toast, live count, Inbox list) so one response works
    # from any page; htmx drops OOB targets that are not on screen.
    create_ticket(org, title, body=request.POST.get("spec", "").strip(),
                  area=area, source="human")
    return _inbox_result(request, org,
                         f"Captured in {area.name if area else 'Inbox'}.")


_REVIEWABLE_TICKET_STATUSES = {"dismissed", "duplicate"}


def inbox(request):
    """The Inbox (open tickets), plus a ?status= review surface for tickets that
    were triaged away — same URL, same list, mirroring the Board's shipped
    archive. Without it a dismissal is a one-way door with nothing on the
    other side."""
    org = get_current_org(request)
    status = request.GET.get("status")
    resolved_view = status if status in _REVIEWABLE_TICKET_STATUSES else ""
    return render(request, "web/inbox.html", {
        "tickets": query_tickets(org, status=resolved_view or "open"),
        "areas": list(list_areas(org)),
        "statuses": _SLICE_STATUSES,
        "resolved_view": resolved_view,
        "dismissed_count": ticket_queryset(org, status="dismissed").count(),
    })


def _inbox_result(request, org, message, *, resolved_view="", undo_url="", undo_label="Undo"):
    """Response for an action that moves a ticket out of (or back into) the
    Inbox: OOB-swap the whole list — so the empty state reappears — plus the
    sidebar count and a toast. The row itself needs no target; the caller uses
    hx-swap="none".

    `resolved_view` names the list the user is looking at, so restoring from
    ?status=dismissed re-renders the dismissed list rather than swapping the
    open one in under a "Dismissed" heading."""
    resp = render(request, "web/partials/_capture_result.html", {
        "tickets": query_tickets(org, status=resolved_view or "open"),
        "areas": list(list_areas(org)),
        "statuses": _SLICE_STATUSES,
        "resolved_view": resolved_view,
        "dismissed_count": ticket_queryset(org, status="dismissed").count(),
        "toast_message": message,
        "undo_url": undo_url,
        "undo_label": undo_label,
    })
    # Home/Board show derived counts that these OOB swaps do not touch.
    return refresh_rollup(request, resp)


def _ticket_or_404(org, ticket_id):
    try:
        return get_ticket(org, ticket_id)
    except NotFound:
        raise Http404


def _ticket_modal(request, org, ticket):
    """The one place a Ticket's full body is readable and editable. Rendered
    into #ticket-modal by htmx, and reachable directly via ?ticket=<id> so
    Attention rows and refreshes can land on a specific ticket."""
    return render(request, "web/partials/_ticket_modal.html", {
        "ticket": ticket,
        "areas": list(list_areas(org)),
        "body_html": render_markdown_html(ticket.body),
        "promoted_slice": getattr(ticket, "slice", None),
        # Release is offered only on absorbed tickets: the origin gave the
        # slice its ref and release_ticket() refuses it.
        "is_origin": ticket.slice is not None and origin_ticket(ticket.slice) == ticket,
    })


def ticket_detail(request, ticket_id):
    org = get_current_org(request)
    return _ticket_modal(request, org, _ticket_or_404(org, ticket_id))


def ticket_edit(request, ticket_id):
    """Autosaved title/body edits from the modal — humans author tickets too,
    not just agents (the same reversal Bites got)."""
    org = get_current_org(request)
    ticket = _ticket_or_404(org, ticket_id)
    kwargs = {}
    if "title" in request.POST:
        title = request.POST["title"].strip()
        if not title:
            return HttpResponse("Title is required", status=400)
        kwargs["title"] = title
    if "body" in request.POST:
        kwargs["body"] = request.POST["body"]
    if kwargs:
        ticket = update_ticket(ticket, actor="human", **kwargs)
    html = render_to_string("web/partials/_ticket_modal.html", {
        "ticket": ticket,
        "areas": list(list_areas(org)),
        "body_html": render_markdown_html(ticket.body),
        "promoted_slice": getattr(ticket, "slice", None),
        # Release is offered only on absorbed tickets: the origin gave the
        # slice its ref and release_ticket() refuses it.
        "is_origin": ticket.slice is not None and origin_ticket(ticket.slice) == ticket,
    }, request=request)
    # The row behind the modal shows title and a body preview — keep it in step.
    return HttpResponse(html + render_to_string(
        "web/partials/_ticket_list.html",
        {"tickets": query_tickets(org), "areas": list(list_areas(org)),
         "statuses": _SLICE_STATUSES, "oob": True},
        request=request,
    ))


def ticket_dismiss(request, ticket_id):
    """Triage a ticket away without building it. Recoverable: it stays readable
    under ?status=dismissed and can be restored from there."""
    org = get_current_org(request)
    ticket = _ticket_or_404(org, ticket_id)
    resolve_ticket(ticket, "dismissed", actor="human")
    return _inbox_result(
        request, org, "Dismissed.",
        undo_url=reverse("web:ticket_reopen", args=[org.slug, ticket.id]),
    )


def ticket_reopen(request, ticket_id):
    org = get_current_org(request)
    try:
        reopen_ticket(_ticket_or_404(org, ticket_id), actor="human")
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    # Restore is only reachable from the dismissed review list — stay on it.
    return _inbox_result(request, org, "Back in the Inbox.", resolved_view="dismissed")


def ticket_promote(request, ticket_id):
    """Promote an Inbox Ticket into a Slice, in one action: pick the area (and
    optionally set an initial status other than the promoted default). Status
    is validated before anything is mutated, so an invalid status 400s without
    leaving the ticket half-promoted."""
    from tuckit.core.models import Slice
    from tuckit.core.services.validation import validate_choice

    org = get_current_org(request)
    area_id = request.POST.get("area_id")
    status = request.POST.get("status")
    try:
        ticket = get_ticket(org, ticket_id)
        area = get_area(org, int(area_id)) if area_id else None
    except NotFound:
        raise Http404
    if area is None:
        return HttpResponse("Choose an area", status=400)
    if status:
        try:
            validate_choice(status, Slice.STATUS_CHOICES, "status")
        except InvalidValue as e:
            return HttpResponse(str(e), status=400)
    try:
        # Idempotent for a double-submit; only a non-open ticket (already
        # dismissed) reaches the error path.
        slice_ = promote_ticket(ticket, area=area, actor="human")
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    if status and status != slice_.status:
        set_slice_status(slice_, status, actor="human")
    return _inbox_result(request, org, "Promoted to a slice.")


def area_create(request):
    org = get_current_org(request)
    create_area(org, request.POST["name"], description=request.POST.get("description", ""))
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
        status = request.POST.get("status", "planned") or "planned"
        spec = request.POST.get("spec", "").strip()
        tags = [t.strip() for t in request.POST.getlist("tags") if t.strip()]
        try:
            create_slice(target, title, spec=spec, status=status, tags=tags, source="human")
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


def ticket_slice_options(request):
    """`<option>` list for the merge select, scoped to one area. An org-wide
    slice dropdown would be unusable within months; scoping keeps it bounded
    without introducing a search widget."""
    org = get_current_org(request)
    area_id = request.GET.get("merge_area_id")
    slices = []
    if area_id:
        try:
            # query_slices takes org first; `area` is keyword-only.
            slices = list(query_slices(org, area=get_area(org, int(area_id))))
        except (NotFound, ValueError):
            slices = []
    return render(request, "web/partials/_slice_options.html", {"slices": slices})


def ticket_merge(request, ticket_id):
    """Fold this ticket into an existing slice instead of promoting it into a
    new one — the human path for what absorb_ticket does over MCP."""
    org = get_current_org(request)
    try:
        ticket = get_ticket(org, ticket_id)
        target = get_slice(org, int(request.POST["slice_id"]))
    except (NotFound, KeyError, ValueError):
        raise Http404
    try:
        absorb_ticket(ticket, target, actor="human")
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return _inbox_result(request, org, "Merged.")


def ticket_release(request, ticket_id):
    """Undo a merge: detach an absorbed ticket and send it back to the Inbox."""
    org = get_current_org(request)
    ticket = _ticket_or_404(org, ticket_id)
    try:
        release_ticket(ticket, actor="human")
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return _inbox_result(request, org, "Released to Inbox.")
