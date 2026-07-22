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
    if org and status in ROADMAP_STATUS_KEYS:
        # Focused single-status flat list — the "view all" / archive surface.
        state = roadmap_state(org)
        return render(request, "web/roadmap.html", {
            "filter_status": status,
            "filter_slices": state.get(status, []),
            "show_area": True,
        })

    view = "list" if request.GET.get("view") == "list" else "board"
    board = roadmap_board_view(org) if org else {
        "state": {}, "groups": [], "shipped_total": 0, "shipped_hidden": 0,
    }
    return render(request, "web/roadmap.html", {
        "state": board["state"],
        "groups": board["groups"],
        "view": view,
        "has_any_slice": any(v for k, v in board["state"].items() if k != "shipped") or board["shipped_total"] > 0,
        # Board tab spans every area, so surface each slice's area on its card/row.
        "show_area": True,
        "board_scope": True,
        "shipped_total": board["shipped_total"],
        "shipped_hidden": board["shipped_hidden"],
    })


def areas(request):
    org = get_current_org(request)
    cards = []
    if org:
        from tuckit.core.services.areas import list_areas
        from tuckit.core.models import Slice
        for a in list_areas(org):
            counts = {}
            for s in Slice.objects.filter(area=a).exclude(status="dropped").values_list("status", flat=True):
                counts[s] = counts.get(s, 0) + 1
            cards.append({
                "area": a,
                "total": sum(counts.values()),
                "building": counts.get("building", 0),
                "shipped": counts.get("shipped", 0),
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
