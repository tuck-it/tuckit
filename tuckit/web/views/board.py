from django.db import transaction
from django.http import Http404, HttpResponse

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.resolve import get_slice
from tuckit.core.services.slices import set_slice_status, reorder_slice
from tuckit.web.auth import get_current_workspace


def slice_move(request, slice_id):
    ws = get_current_workspace(request)
    try:
        slice_ = get_slice(ws, slice_id)
    except NotFound:
        raise Http404

    before = after = None
    if request.POST.get("before_id"):
        try: before = get_slice(ws, int(request.POST["before_id"]))
        except NotFound: raise Http404
    if request.POST.get("after_id"):
        try: after = get_slice(ws, int(request.POST["after_id"]))
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

    return HttpResponse(status=204)
