from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.resolve import get_slice, get_bite, get_area
from tuckit.core.services.slices import set_slice_status, update_slice, set_slice_area
from tuckit.core.services.bites import create_bite, delete_bite, set_bite_status, update_bite
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import widget_oob
from tuckit.web.detail import slice_detail_context


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
    slice_ = _slice_or_404(request, slice_id)
    try:
        set_slice_status(slice_, request.POST["status"])
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return _detail(request, slice_)


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

    Reuses capture._inbox_result() for the toast + OOB list/count refresh
    rather than re-rendering the detail panel the way slice_reassign() does:
    this fires from the Inbox list, not a slice's own page, so there is no
    detail panel on screen to update."""
    from tuckit.web.views.capture import _inbox_result

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
    return _inbox_result(
        request, org, message,
        undo_url=reverse("web:slice_area", args=[org.slug, slice_.id]),
        undo_label="Undo",
        # A bare re-POST to undo_url clears the area (area_id defaults to "").
        # That is correct for undoing a *file*, but undoing a *clear* needs to
        # restore whatever area it left — hence the old area rides along as
        # the value Undo will submit.
        undo_area_id=old.id if old else "",
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
