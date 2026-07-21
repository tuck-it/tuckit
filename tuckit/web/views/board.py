from django.db import transaction
from django.http import Http404, HttpResponse

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.resolve import get_slice
from tuckit.core.services.slices import set_slice_status, reorder_slice
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import refresh_rollup


def slice_move(request, slice_id):
    org = get_current_org(request)
    try:
        slice_ = get_slice(org, slice_id)
    except NotFound:
        raise Http404

    before = after = None
    if request.POST.get("before_id"):
        try: before = get_slice(org, int(request.POST["before_id"]))
        except NotFound: raise Http404
    if request.POST.get("after_id"):
        try: after = get_slice(org, int(request.POST["after_id"]))
        except NotFound: raise Http404

    status = request.POST.get("status")

    with transaction.atomic():
        if status and status != slice_.status:
            try:
                set_slice_status(slice_, status)
            except InvalidValue as e:
                return HttpResponse(str(e), status=400)
        if before is not None or after is not None:
            reorder_slice(slice_, before=before, after=after)

    # Two callers now. SortableJS updates the DOM optimistically and ignores the
    # body, so 204 is still right for a drag. The card's status buttons (the
    # non-drag alternative, WCAG 2.5.7) come in via htmx from the Board itself,
    # which is a derived roll-up — refresh_rollup re-renders the columns so the
    # card visibly lands in its new one.
    return refresh_rollup(request, HttpResponse(status=204))
