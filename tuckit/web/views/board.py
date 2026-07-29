from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse
from django.urls import reverse

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.resolve import get_slice
from tuckit.core.services.slices import set_slice_status, reorder_slice
from tuckit.web.auth import get_current_org
from tuckit.web.htmx import refresh_rollup
from tuckit.web.views._feedback import slice_status_message


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
            old_status = slice_.status
            try:
                set_slice_status(slice_, status)
            except InvalidValue as e:
                return HttpResponse(str(e), status=400)
            # The response below is a bare 204 — SortableJS ignores the body on
            # a drag, and even the card's status buttons get nothing to swap an
            # OOB toast into, because this view is always called from the Board
            # (an 'area' roll-up view — see refresh_rollup), so HX-Refresh below
            # always fires a full page reload right after. An HX-Trigger toast
            # would flash and vanish under that reload; a queued message
            # survives it and is what base.html's `{% for m in messages %}`
            # loop already plays through the same showToast() on the next page,
            # the same channel Task 10 built for the ticket-deep-link redirect.
            # Undo rides the URL's query string (mutations.slice_status reads
            # `?undo_status=` as a fallback), not a request body: the button
            # showToast() builds from a queued message is a bare POST with
            # nowhere to attach hx-vals.
            messages.success(
                request, slice_status_message(old_status, slice_.status),
                extra_tags=reverse("web:slice_status", args=[org.slug, slice_.id])
                          + f"?undo_status={old_status}",
            )
        if before is not None or after is not None:
            reorder_slice(slice_, before=before, after=after)

    # Two callers now. SortableJS updates the DOM optimistically and ignores the
    # body, so 204 is still right for a drag. The card's status buttons (the
    # non-drag alternative, WCAG 2.5.7) come in via htmx from the Board itself,
    # which is a derived roll-up — refresh_rollup re-renders the columns so the
    # card visibly lands in its new one.
    return refresh_rollup(request, HttpResponse(status=204))
