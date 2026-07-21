from urllib.parse import urlparse

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.areas import create_area, list_areas, update_area, delete_area, reorder_area
from tuckit.core.services.slices import create_slice, set_slice_status, grouped_slices
from tuckit.core.services.tickets import (
    create_ticket, query_tickets, ticket_queryset, promote_ticket, reopen_ticket,
    resolve_ticket,
)
from tuckit.core.services.resolve import get_area, get_ticket, get_area_by_slug
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import redirect_response, widget_oob

_SLICE_STATUSES = ["planned", "building", "shipped"]


def capture(request):
    """Global capture. Title is required; area/status/spec/tags are optional.
    A bare title stays a quick, unfiled Inbox capture — it becomes a Ticket, not
    a Slice, since there's no "Inbox area" to place a Slice in. Any authored
    detail (an area, a spec, tags, or a non-default status) requires an area and
    creates a full Slice, redirecting the user into it. Bites live under a
    Slice's Plan section, where a human or an agent can author them."""
    org = get_current_org(request)

    title = request.POST.get("title", "").strip()
    if not title:
        return HttpResponse("Title is required", status=400)

    status = request.POST.get("status", "planned") or "planned"
    spec = request.POST.get("spec", "").strip()
    tags = [t.strip() for t in request.POST.getlist("tags") if t.strip()]

    area = None
    if request.POST.get("area_id"):
        try:
            area = get_area(org, int(request.POST["area_id"]))
        except (NotFound, ValueError):
            raise Http404

    # "Rich" = the user authored beyond a bare title-into-Inbox capture.
    rich = bool(spec or tags or area is not None or status != "planned")

    if not rich:
        # Quick path: an unfiled Ticket — bundle out-of-band swaps: a
        # confirmation toast, the live inbox count, and an OOB re-render of the
        # Inbox list (lands only if that page is open; htmx ignores OOB targets
        # absent from the current page, so one response fits every page).
        create_ticket(org, title, source="human")
        return _inbox_result(request, org, "Captured in Inbox.")

    if area is None:
        return HttpResponse("Choose an area to save more than a quick note.", status=400)

    try:
        slice_ = create_slice(area, title, spec=spec, status=status, tags=tags, source="human")
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)

    # Land in the freshly authored slice to keep working (full navigation).
    return redirect_response(request, "web:slice", org_slug=org.slug, slice_id=slice_.id)


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


def _inbox_result(request, org, message, *, resolved_view=""):
    """Response for an action that moves a ticket out of (or back into) the
    Inbox: OOB-swap the whole list — so the empty state reappears — plus the
    sidebar count and a toast. The row itself needs no target; the caller uses
    hx-swap="none".

    `resolved_view` names the list the user is looking at, so restoring from
    ?status=dismissed re-renders the dismissed list rather than swapping the
    open one in under a "Dismissed" heading."""
    return render(request, "web/partials/_capture_result.html", {
        "tickets": query_tickets(org, status=resolved_view or "open"),
        "areas": list(list_areas(org)),
        "statuses": _SLICE_STATUSES,
        "resolved_view": resolved_view,
        "dismissed_count": ticket_queryset(org, status="dismissed").count(),
        "toast_message": message,
    })


def ticket_dismiss(request, ticket_id):
    """Triage a ticket away without building it. Recoverable: it stays readable
    under ?status=dismissed and can be restored from there."""
    org = get_current_org(request)
    try:
        ticket = get_ticket(org, ticket_id)
    except NotFound:
        raise Http404
    resolve_ticket(ticket, "dismissed", actor="human")
    return _inbox_result(request, org, "Dismissed.")


def ticket_reopen(request, ticket_id):
    org = get_current_org(request)
    try:
        ticket = get_ticket(org, ticket_id)
    except NotFound:
        raise Http404
    try:
        reopen_ticket(ticket, actor="human")
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
    return HttpResponse(html + widget_oob(request))


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
    groups = grouped_slices(area)
    has_any_slice = any(items for _, items in groups)
    html = render_to_string("web/partials/_area_list.html", {
        "area": area,
        "groups": groups,
        "has_any_slice": has_any_slice,
    }, request=request)
    return HttpResponse(html + widget_oob(request))
