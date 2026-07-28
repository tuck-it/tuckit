from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from tuckit.core.services.state import (
    home_state,
    your_turn,
    since_last_visit,
    mark_home_seen,
    roadmap_state,
    roadmap_board_view,
    ROADMAP_STATUS_KEYS,
    cap_shipped,
    snapshot_today,
)
from tuckit.web.auth import get_current_org
from tuckit.core.models import Slice

# The two shared predicates split the world in half but do not cover it:
# inbox_filter() is `area IS NULL AND status = 'open'` and filed_slices() is
# `area IS NOT NULL`, so an area-less slice that was shipped or dropped falls
# between them. 0045 produced exactly those rows in production (every
# dismissed/duplicate ticket became status='dropped' while keeping its NULL
# area), which is why the archive lists below deliberately do NOT route through
# filed_slices(): they are the only surface those slices can be read from once
# the legacy ?ticket= redirect goes away in 0047.
ARCHIVE_STATUSES = ("shipped", "dropped")


def home(request):
    """Four stacked bands: what needs you, what changed while you were away,
    what's in flight, what shipped. No stat cards — every number they carried
    was the length of a list further down the same page."""
    org = get_current_org(request)
    if org is None:
        return render(request, "web/home.html", {"org": None})

    state = home_state(org)
    turn = your_turn(org)
    # Written for history only; nothing on this page reads it back.
    snapshot_today(org, state, len(turn))

    member = (
        org.members.filter(user=request.user).first()
        if request.user.is_authenticated else None
    )
    # Order is load-bearing: compute what's new against the old watermark, THEN
    # advance it. Reversed, the band would badge zero forever.
    activity = since_last_visit(org, member)
    mark_home_seen(member)

    visible, shipped_total = cap_shipped(org, state["shipped"])

    return render(request, "web/home.html", {
        "org": org,
        "state": {**state, "shipped": visible},
        "your_turn": turn,
        "activity": activity["events"],
        "activity_new": activity["new_count"],
        "shipped_total": shipped_total,
        "shipped_hidden": shipped_total - len(visible),
    })


def roadmap(request):
    org = get_current_org(request)
    status = request.GET.get("status")
    if org and (status in ROADMAP_STATUS_KEYS or status == "dropped"):
        # Focused single-status flat list — the "view all" / archive surface.
        if status in ARCHIVE_STATUSES:
            # No filed_slices() here (see ARCHIVE_STATUSES above): a shipped or
            # dropped slice with no area is in no Inbox (inbox_filter pins
            # status='open') and on no Area board, so this list is where it has
            # to show up. It renders with an "Inbox" chip instead of an area
            # name. NULL sorts fine in SQL, so the ordering Task 11 wanted
            # costs nothing.
            qs = (
                Slice.objects.filter(org=org, status=status)
                .select_related("area", "org").prefetch_related("tags")
            )
            if status == "shipped":
                # Recency, matching roadmap_state()'s shipped bucket — this is
                # the "view all" behind the same board link, uncapped.
                filter_slices = sorted(
                    qs, key=lambda s: (s.completed_at or s.updated_at), reverse=True,
                )
            else:
                filter_slices = list(qs.order_by("area__name", "rank"))
        else:
            filter_slices = roadmap_state(org).get(status, [])
        return render(request, "web/roadmap.html", {
            "filter_status": status,
            "filter_slices": filter_slices,
            "show_area": True,
        })

    view = "list" if request.GET.get("view") == "list" else "board"
    board = roadmap_board_view(org) if org else {
        "groups": [], "shipped_total": 0, "shipped_hidden": 0, "dropped_count": 0,
    }
    groups = board["groups"]
    has_any = (
        any(slices for _, slices in groups)
        or board["shipped_total"] > 0
        or board["dropped_count"] > 0
    )
    return render(request, "web/roadmap.html", {
        "groups": groups,
        "view": view,
        "has_any_slice": has_any,
        # Board tab spans every area, so surface each slice's area on its card/row.
        "show_area": True,
        "board_scope": True,
        "shipped_total": board["shipped_total"],
        "shipped_hidden": board["shipped_hidden"],
        "dropped_count": board["dropped_count"],
    })


def areas(request):
    org = get_current_org(request)
    cards = []
    if org:
        from tuckit.core.services.areas import list_areas
        from tuckit.core.services.slices import annotate_stage_counts, stage_of
        for a in list_areas(org):
            # order_by is explicit: annotate_stage_counts drops Meta.ordering.
            slices = list(
                annotate_stage_counts(
                    Slice.objects.filter(area=a).exclude(status="dropped")
                ).order_by("rank")
            )
            cards.append({
                "area": a,
                "total": len(slices),
                "executing": sum(1 for s in slices if stage_of(s) == "executing"),
                "shipped": sum(1 for s in slices if s.status == "shipped"),
            })
    return render(request, "web/areas.html", {"cards": cards, "is_empty": not cards})


@require_POST
def dismiss_onboarding(request):
    org = get_current_org(request)
    if org is None:
        return redirect("web:root")
    org.onboarding_dismissed = True
    org.save(update_fields=["onboarding_dismissed"])
    return redirect("web:home", org_slug=org.slug)
