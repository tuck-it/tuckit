from django.http import HttpResponse
from django.template.loader import render_to_string

from tuckit.core.services.slices import inbox_slices
from tuckit.web.htmx import refresh_rollup

# One notification surface, two writers: capture.py (Inbox filing) and
# mutations.py (Ship/Drop/Restore/Reopen, Area filing). Both funnel through
# _action_result() below. board.py's slice_move is a third *caller* of the
# same idea but not of this function — its response is a bare 204 (SortableJS
# ignores the body on a drag), so it queues a django.contrib.messages notice
# instead and lets the page reload it, the same "second channel" Task 10 built
# for the ticket-deep-link redirect. Both channels end at the same #toast /
# showToast() in base.html; do not add a third.
#
# This module used to be capture.py's _inbox_result(), private to that file.
# Ship/Drop needed the exact same toast+Undo+OOB-refresh machinery — Restore
# can hand an area-less dropped slice straight back to the Inbox (0045 mapped
# dismissed/duplicate tickets to dropped slices, copying their often-NULL
# area), so the Inbox list and its count can legitimately need refreshing from
# a status change too — so the function moved here and lost its Inbox-only
# name.


def _action_result(request, org, message, *, undo_url="", undo_label="Undo", undo_area_id=None,
                    close_detail=True, lead_html=""):
    """Response for a Slice action that a toast should announce: filing/
    clearing an Area (capture, the Inbox row, the panel's Area picker) or a
    status change (Ship/Drop/Restore/Reopen). OOB-swap the whole Inbox list —
    so the empty state reappears — plus the sidebar count and a toast. The
    triggering element itself needs no target; area callers use hx-swap="none"
    and status callers already target `.detail-body` directly, so the toast/
    count/list ride along as OOB siblings of whatever `lead_html` is.

    `undo_area_id` is the Area-filing Undo's old value (None -> Inbox, else
    that area's id): a bare re-POST to `undo_url` with no body always clears
    the area, correct for undoing a *file* but a no-op for undoing a *clear*,
    so the toast's Undo button carries the OLD area back as `area_id`. A
    status-change Undo does not use this — `mutations.slice_status` threads
    its old value through `undo_url`'s own query string instead
    (`?undo_status=`), so its Undo button can stay a bare, valueless POST too;
    leave `undo_area_id` at its default None for those callers.

    `lead_html` rides at the END of the OOB bundle; `close_detail=False` keeps
    the open detail panel alive. Both exist for actions that grow (or
    collapse) the panel the user is looking at instead of wiping it: the
    Area picker INSIDE the panel (Task 10) and now Ship/Drop/Restore/Reopen
    (Task 12) — the panel comes back re-rendered, not cleared.

    ORDER IS LOAD-BEARING, and it used to be the other way round. `lead_html`
    replaces `.detail-body` wholesale (outerHTML), and every control that can
    send `from=detail` — the area menu, "Move to Inbox", Ship/Drop — lives
    INSIDE that panel. Put that swap first and it detaches the element that
    issued the request before htmx has processed the rest of the bundle, so
    the toast, the sidebar count, the Inbox list and the page-head count were
    all silently dropped: the action landed, the panel grew, and the user got
    no confirmation and no Undo. Browser-verified, and invisible to endpoint
    tests — the response carried all five fragments in both orders, only the
    client behaved differently (cf. the hx-swap inheritance class of bug).
    Anything that destroys the requesting element goes LAST."""
    html = render_to_string("web/partials/_capture_result.html", {
        "slices": list(inbox_slices(org)),
        "toast_message": message,
        "undo_url": undo_url,
        "undo_label": undo_label,
        "undo_area_id": undo_area_id,
        "close_detail": close_detail,
    }, request=request) + lead_html
    # Home/Board show derived counts that these OOB swaps do not touch.
    return refresh_rollup(request, HttpResponse(html))


def slice_status_message(old_status: str, new_status: str) -> str:
    """English toast copy for a Ship/Drop/Restore/Reopen transition. Shared
    between mutations.slice_status (the detail panel's own buttons) and
    board.slice_move (the Board's status buttons and drag) so the same action
    reads the same sentence regardless of which surface it was done from."""
    if new_status == "shipped":
        return "Shipped."
    if new_status == "dropped":
        return "Dropped."
    if new_status == "open":
        return "Restored." if old_status == "dropped" else "Reopened."
    return "Updated."
