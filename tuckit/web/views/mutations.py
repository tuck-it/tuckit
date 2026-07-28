from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.resolve import get_slice, get_bite, get_area
from tuckit.core.services.slices import set_slice_status, update_slice, set_slice_area
from tuckit.core.services.bites import create_bite, delete_bite, set_bite_status, update_bite
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import widget_oob
from tuckit.web.detail import slice_detail_context
from tuckit.web.views._feedback import _action_result, slice_status_message


def _slice_or_404(request, slice_id):
    try:
        return get_slice(get_current_org(request), slice_id)
    except NotFound:
        raise Http404


def _detail(request, slice_):
    is_modal = request.GET.get("modal") == "1"
    resp = render(
        request, "web/partials/_slice_detail.html",
        slice_detail_context(slice_, is_modal=is_modal),
    )
    # Append the onboarding widget OOB so detail-level mutations (add a step,
    # etc.) tick the matching onboarding step immediately. Empty when the widget
    # is hidden, so this is a no-op once onboarding is done or dismissed.
    resp.write(widget_oob(request))
    return resp


def slice_status(request, slice_id):
    """Ship / Drop / Restore / Reopen. None of the four is a one-way door —
    the release's whole claim is that nothing is — so the status the slice is
    LEAVING is exactly what Undo needs to resubmit. It rides on the query
    string (`?undo_status=`) rather than the request body: that lets the same
    plain "POST, no body" Undo button work both here (the OOB toast's real
    <button hx-post>) and from board.slice_move's queued-message toast, which
    has no hx-vals to attach a body to and cannot safely carry one anyway (its
    response is a bare 204 followed by a full-page reload, so anything it
    hands back has to survive in the URL, not in form data).

    Routes through _action_result() — the same toast/Undo/OOB-refresh
    machinery Inbox filing and Area-picking already use — because Restore can
    hand an area-less dropped slice straight back to the Inbox (0045 mapped
    dismissed/duplicate tickets to dropped slices, copying their often-NULL
    area), so the Inbox list and its count can legitimately need refreshing
    from a status change too. `close_detail=False`: the whole point is that
    the panel re-renders in place with its new stage/action-bar, not that it
    closes."""
    slice_ = _slice_or_404(request, slice_id)
    org = get_current_org(request)
    old_status = slice_.status
    new_status = request.POST.get("status") or request.GET.get("undo_status", "")
    try:
        set_slice_status(slice_, new_status)
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)

    is_modal = request.GET.get("modal") == "1"
    ctx = slice_detail_context(slice_, is_modal=is_modal)
    lead_html = render_to_string("web/partials/_slice_detail.html", ctx, request=request)
    lead_html += widget_oob(request)

    undo_qs = f"?undo_status={old_status}" + ("&modal=1" if is_modal else "")
    return _action_result(
        request, org, slice_status_message(old_status, slice_.status),
        undo_url=reverse("web:slice_status", args=[org.slug, slice_.id]) + undo_qs,
        undo_label="Undo",
        close_detail=False,
        lead_html=lead_html,
    )


def slice_edit(request, slice_id):
    slice_ = _slice_or_404(request, slice_id)
    kwargs = {}
    if "title" in request.POST: kwargs["title"] = request.POST["title"]
    if "spec" in request.POST: kwargs["spec"] = request.POST["spec"]
    # constraints is a Slice field now, edited from the panel exactly like spec
    # (it used to be reachable only through a Plan, which is why it was almost
    # never filled in).
    if "constraints" in request.POST: kwargs["constraints"] = request.POST["constraints"]
    update_slice(slice_, **kwargs)
    return _detail(request, slice_)


def slice_reassign(request, slice_id):
    slice_ = _slice_or_404(request, slice_id)
    try:
        area = get_area(get_current_org(request), int(request.POST["area_id"]))
    except (NotFound, ValueError, KeyError):
        raise Http404
    set_slice_area(slice_, area)
    return _detail(request, slice_)


@require_POST
def slice_area(request, slice_id):
    """The Inbox row's one control: file a slice into an Area, or clear it
    (empty area_id) to send it back to the Inbox. Both directions are the
    same endpoint on purpose — un-triaging is un-picking an area, not a
    separate "undo promote" action, because there is no promotion left to
    undo.

    Reuses _feedback._action_result() for the toast + OOB list/count refresh.

    `from=detail` (sent by the picker inside the detail panel) adds the
    re-rendered panel to that same response, OOB-swapped over `.detail-body`.
    That is the interaction this release is built on: pick an area and the
    panel GROWS — stage, constraints, steps, activity, Ship/Drop — clear it and
    it collapses back, with the modal staying open through both. Without it the
    modal closed on you and the full page kept showing the un-grown panel while
    the toast said "Filed in Backend", i.e. the screen contradicted itself.

    htmx skips an OOB swap whose target is not on screen, but the panel is
    still gated on the marker rather than sent always: the Inbox row fires the
    same endpoint, and a `.detail-body` on that page could only be some OTHER
    slice's panel."""
    org = get_current_org(request)
    slice_ = _slice_or_404(request, slice_id)
    raw = request.POST.get("area_id") or ""
    try:
        area = get_area(org, int(raw)) if raw else None
    except (NotFound, ValueError):
        raise Http404
    old = slice_.area
    set_slice_area(slice_, area)
    message = f"Filed in {area.name}." if area else "Moved back to Inbox."
    from_detail = request.POST.get("from") == "detail"
    is_modal = request.GET.get("modal") == "1"
    lead_html = ""
    if from_detail:
        ctx = slice_detail_context(slice_, is_modal=is_modal)
        ctx["oob"] = True
        lead_html = render_to_string("web/partials/_slice_detail.html", ctx, request=request)
        lead_html += widget_oob(request)
    return _action_result(
        request, org, message,
        # ?modal=1 has to survive onto the Undo URL as well, or undoing from an
        # open modal re-renders the panel without its card chrome.
        undo_url=reverse("web:slice_area", args=[org.slug, slice_.id])
                 + ("?modal=1" if from_detail and is_modal else ""),
        undo_label="Undo",
        # A bare re-POST to undo_url clears the area (area_id defaults to "").
        # That is correct for undoing a *file*, but undoing a *clear* needs to
        # restore whatever area it left — hence the old area rides along as
        # the value Undo will submit.
        undo_area_id=old.id if old else "",
        close_detail=not from_detail,
        lead_html=lead_html,
    )


# The three plan mutations (create/edit/delete) are gone with the plan card
# that was their only caller. Nothing in the product creates a Plan any more:
# `constraints` is a Slice field and steps hang off the Slice. The model and
# its service survive this release only so 0045's data stays readable until
# 0047 drops the table (Task 13 retires the MCP tools).


def slice_tags(request, slice_id):
    slice_ = _slice_or_404(request, slice_id)
    names = [t.name for t in slice_.tags.all()]
    add = request.POST.get("add", "").strip()
    remove = request.POST.get("remove", "").strip()
    if add and add not in names:
        names.append(add)
    if remove and remove in names:
        names.remove(remove)
    update_slice(slice_, tags=names)
    return render(request, "web/partials/_slice_tags.html", {"slice": slice_})


def bite_toggle(request, bite_id):
    try:
        bite = get_bite(get_current_org(request), bite_id)
    except NotFound:
        raise Http404
    set_bite_status(bite, "todo" if bite.status == "done" else "done")
    return render(request, "web/partials/_bite_row.html", {"bite": bite})


def bite_body(request, bite_id):
    try:
        bite = get_bite(get_current_org(request), bite_id)
    except NotFound:
        raise Http404
    update_bite(bite, body=request.POST.get("body", ""))
    return render(request, "web/partials/_bite_row.html", {"bite": bite})


def bite_create(request, slice_id):
    """Add a step. Straight onto the Slice — the plan-scoped route
    (POST /plans/<id>/bites) and the shim that reparented each new bite onto
    the submitting plan are both gone, because the panel no longer groups
    steps by plan."""
    slice_ = _slice_or_404(request, slice_id)
    title = request.POST.get("title", "").strip()
    if not title:
        return HttpResponse("Title is required", status=400)
    create_bite(slice_, title, source="human")
    return _detail(request, slice_)


def bite_edit(request, bite_id):
    try:
        bite = get_bite(get_current_org(request), bite_id)
    except NotFound:
        raise Http404
    if "title" in request.POST:
        update_bite(bite, title=request.POST["title"])
    return _detail(request, bite.slice)


def bite_delete(request, bite_id):
    try:
        bite = get_bite(get_current_org(request), bite_id)
    except NotFound:
        raise Http404
    slice_ = bite.slice
    delete_bite(bite)
    return _detail(request, slice_)
