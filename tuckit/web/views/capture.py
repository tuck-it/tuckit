from urllib.parse import urlparse

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.areas import get_or_create_triage, create_area, list_areas, update_area, delete_area, reorder_area
from tuckit.core.services.slices import create_slice, set_slice_area, set_slice_status, list_slices, grouped_slices
from tuckit.core.services.resolve import get_area, get_slice, get_area_by_slug
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import redirect_response, widget_oob


def capture(request):
    """Global capture. Title is required; area/status/spec/tags are optional.
    A bare title stays a quick Inbox capture (OOB toast bundle, modal keeps
    capturing); any authored detail creates a full slice and redirects the
    user into it. Bites live under a Slice's Plan section, where a human or an
    agent can author them."""
    org = get_current_org(request)

    title = request.POST.get("title", "").strip()
    if not title:
        return HttpResponse("Title is required", status=400)

    status = request.POST.get("status", "idea") or "idea"
    spec = request.POST.get("spec", "").strip()
    tags = [t.strip() for t in request.POST.getlist("tags") if t.strip()]

    area = None
    if request.POST.get("area_id"):
        try:
            area = get_area(org, int(request.POST["area_id"]))
        except (NotFound, ValueError):
            raise Http404

    triage = get_or_create_triage(org)
    target_area = area or triage

    # "Rich" = the user authored beyond a bare title-into-Inbox capture.
    rich = bool(
        spec or tags
        or (area is not None and not area.is_triage)
        or status != "idea"
    )

    try:
        slice_ = create_slice(target_area, title, spec=spec, status=status, tags=tags, source="human")
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)

    if rich:
        # Land in the freshly authored slice to keep working (full navigation).
        return redirect_response(request, "web:slice", org_slug=org.slug, slice_id=slice_.id)

    # Quick path — bundle out-of-band swaps: a confirmation toast, the live
    # count, and an OOB re-render of the Triage list (lands only if that page is
    # open; htmx ignores OOB targets absent from the current page, so one
    # response fits every page).
    return render(request, "web/partials/_capture_result.html", {
        "slices": list(list_slices(triage).prefetch_related("tags")),
        "areas": [a for a in list_areas(org) if not a.is_triage],
        "statuses": ["idea", "planned", "building", "shipped"],
    })


def triage_list(request):
    org = get_current_org(request)
    triage_area = get_or_create_triage(org)
    return render(request, "web/triage.html", {
        "slices": list(list_slices(triage_area).prefetch_related("tags")),
        "areas": [a for a in list_areas(org) if not a.is_triage],
        "statuses": ["idea", "planned", "building", "shipped"],
    })


def triage(request, slice_id):
    org = get_current_org(request)
    area_id = request.POST.get("area_id")
    try:
        slice_ = get_slice(org, slice_id)
        area = get_area(org, int(area_id)) if area_id else None
    except NotFound:
        raise Http404
    try:
        set_slice_status(slice_, request.POST["status"])
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    if area_id:
        set_slice_area(slice_, area)
    return HttpResponse(status=204)  # htmx removes the row via hx-swap


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
        status = request.POST.get("status", "idea") or "idea"
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
