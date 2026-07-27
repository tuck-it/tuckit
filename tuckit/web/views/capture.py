from urllib.parse import urlparse

from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.areas import create_area, list_areas, update_area, delete_area, reorder_area
from tuckit.core.services.slices import create_slice, inbox_slices
from tuckit.core.services.state import area_board_view
from tuckit.core.services.tickets import promote_ticket, reopen_ticket, resolve_ticket, update_ticket
from tuckit.web.detail import render_markdown_html
from tuckit.core.services.resolve import get_area, get_ticket, get_area_by_slug, get_slice
from tuckit.core.services.slices import query_slices
from tuckit.core.services.tickets import absorb_ticket, origin_ticket, release_ticket
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import refresh_rollup, widget_oob


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
    return _inbox_result(request, org,
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


def _inbox_result(request, org, message, *, undo_url="", undo_label="Undo", undo_area_id=None):
    """Response for an action that moves a Slice out of (or back into) the
    Inbox: OOB-swap the whole list — so the empty state reappears — plus the
    sidebar count and a toast. The row itself needs no target; the caller uses
    hx-swap="none".

    `undo_area_id` is the area the slice is leaving (None -> Inbox, else that
    area's id). A bare re-POST to `undo_url` with no body always clears the
    area — correct for undoing a file, but a no-op for undoing a clear. Passing
    it lets the toast's Undo button carry the OLD area back as `area_id`, so
    Undo reverses whichever direction actually happened, not just one of them.

    Also reused by the (still-live) Ticket triage modal's actions — those OOB
    targets are simply absent outside the Inbox page, and htmx silently skips
    an OOB swap with no matching target on screen."""
    resp = render(request, "web/partials/_capture_result.html", {
        "slices": list(inbox_slices(org)),
        "toast_message": message,
        "undo_url": undo_url,
        "undo_label": undo_label,
        "undo_area_id": undo_area_id,
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
    # No more row-behind-the-modal to keep in sync: the Inbox no longer lists
    # Tickets at all (Task 9), so _ticket_modal() alone is the whole response.
    return _ticket_modal(request, org, ticket)


def ticket_dismiss(request, ticket_id):
    """Triage a ticket away without building it. Recoverable via Restore in
    the modal itself (ticket_reopen) — there is no browsable review list any
    more (that was the old Ticket-based Inbox's ?status=dismissed, retired
    along with the rest of that screen in Task 9)."""
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
    return _inbox_result(request, org, "Back in the Inbox.")


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


def ticket_slice_options(request):
    """`<option>` list for the triage slice select, scoped to one area. An
    org-wide slice dropdown would be unusable within months; scoping keeps it
    bounded without introducing a search widget.

    "New slice" leads the list in every response, so the select is valid before
    an area is picked and promoting costs no interaction with it at all."""
    from tuckit.core.services.refs import ref_for

    org = get_current_org(request)
    area_id = request.GET.get("area_id")
    slices = []
    if area_id:
        try:
            # query_slices takes org first; `area` is keyword-only.
            slices = list(query_slices(org, area=get_area(org, int(area_id))))
        except (NotFound, ValueError):
            slices = []
    # An <option> cannot hold the markup {% ref_of %} renders, so attach the ref
    # as a plain string. ref_for() keeps the format in services/refs.py, which is
    # the rule that tag exists to enforce.
    for s in slices:
        s.ref = ref_for(s)
    return render(request, "web/partials/_slice_options.html", {"slices": slices})


def ticket_triage(request, ticket_id):
    """Send a ticket somewhere: into a NEW slice in the chosen area, or into an
    EXISTING one.

    These were two endpoints behind two identical-looking "Choose area" selects
    that meant different things — one named where to build, the other only
    filtered a list of slices. That is a single decision ("where does this
    go?"), so it is now one form and one endpoint, and `slice_id` is its branch.

    This is the Ticket modal's own triage action (still live — see
    _ticket_modal.html, reachable from the Area page's Inbox strip). It is
    unrelated to the Slice-based Inbox screen's Area picker (slice_area() in
    mutations.py, POST /slices/<id>/area) — the old ticket_promote() this
    docstring used to distinguish itself from was that screen's one-way
    promote button, retired in Task 9 along with the rest of that row."""
    org = get_current_org(request)
    try:
        ticket = get_ticket(org, ticket_id)
        area = get_area(org, int(request.POST["area_id"]))
    except (NotFound, KeyError, ValueError):
        raise Http404

    # Absent means "new". A form that loses the field must not fall through to
    # merging into some arbitrary slice.
    slice_id = request.POST.get("slice_id") or "new"
    try:
        if slice_id == "new":
            promote_ticket(ticket, area=area, actor="human")
            message = "Promoted to a slice."
        else:
            target = get_slice(org, int(slice_id))
            if target.area_id != area.id:
                # The area select scopes the slice list, so a mismatch means a
                # stale form rather than a deliberate cross-area merge.
                return HttpResponse("That slice is not in the chosen area", status=400)
            absorb_ticket(ticket, target, actor="human")
            message = "Merged."
    except (NotFound, ValueError):
        raise Http404
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return _inbox_result(request, org, message)


def ticket_release(request, ticket_id):
    """Undo a merge: detach an absorbed ticket and send it back to the Inbox."""
    org = get_current_org(request)
    ticket = _ticket_or_404(org, ticket_id)
    try:
        release_ticket(ticket, actor="human")
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return _inbox_result(request, org, "Released to Inbox.")
