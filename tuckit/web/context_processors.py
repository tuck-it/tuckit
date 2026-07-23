from django.db.models import Count, Q

from tuckit.core.services.areas import list_areas
from tuckit.core.services.orgs import accessible_orgs
from tuckit.web.auth import current_org_or_fallback


def sidebar_areas(request):
    """Make the org's areas available to every template so the sidebar's Areas
    list (and active-nav highlighting) is consistent across all pages, not
    just the ones whose view happens to pass `areas` itself.

    `slice_count` is annotated (one extra GROUP BY, no N+1) so the delete
    confirmation can say how much is about to be destroyed rather than the
    unquantified "and all items in it". Dropped slices are excluded to match
    what the Areas overview already calls an area's slice count — a confirm
    saying "3 slices" next to a card saying "2 slices" is its own bug.
    """
    org = current_org_or_fallback(request)
    if not org:
        return {}
    # order_by is explicit because the annotation adds a GROUP BY, and Django
    # does not apply Meta.ordering to aggregate queries — the generated SQL
    # then has no ORDER BY at all. sqlite happens to hand back rowid order, so
    # the sidebar looks right locally while Postgres guarantees nothing and
    # drag-to-reorder silently stops sticking in production.
    return {"areas": list(list_areas(org).annotate(
        slice_count=Count("slices", filter=~Q(slices__status="dropped"))
    ).order_by("rank"))}


def inbox_count(request):
    """Expose the org's open (untriaged) Ticket count to every template so
    the sidebar can show a muted count badge next to Inbox. Runs on every
    request, so it counts in the DB rather than hydrating the rows."""
    from tuckit.core.services.tickets import ticket_queryset

    org = current_org_or_fallback(request)
    if not org:
        return {}
    return {"inbox_count": ticket_queryset(org).count()}


def switchable_orgs(request):
    """Expose the user's accessible orgs to every template so the sidebar
    switcher can list them, regardless of whether the current view happens to
    pass org data itself."""
    if not request.user.is_authenticated:
        return {"switchable_orgs": []}
    return {"switchable_orgs": list(accessible_orgs(request.user))}


def current_org(request):
    """Org used for sidebar chrome. Prefers the request's tenant org; on
    non-tenant pages (settings/account) falls back to the session/first org so the
    sidebar switcher and nav still resolve. Access control is NOT done here — it lives in
    TenantMiddleware."""
    org = current_org_or_fallback(request)
    return {"current_org": org} if org else {}


def auth_chrome(request):
    """Expose auth-screen chrome to every template: whether self-service
    registration is open (controls the login→signup cross-link) and the optional
    marketing-site URL (makes the auth-card wordmark a link home). Read from
    settings per request so tests can override them."""
    from django.conf import settings

    return {
        "registration_open": settings.REGISTRATION_OPEN,
        "marketing_url": getattr(settings, "TUCKIT_MARKETING_URL", "") or "",
    }


def capture_area(request):
    """Preselect the Area a capture lands in when the user is standing on an
    Area page.

    The capture modal lives in base.html, so it never sees the page view's
    context — a template variable set by area_view() would be invisible to it.
    Resolved from request.resolver_match rather than by parsing the path, the
    same way onboarding() decides whether you are already on the newest slice.

    Filing a capture is not the same as committing to it: the preselected area
    only labels the Ticket, it does not turn it into a Slice.
    """
    from tuckit.core.services.exceptions import NotFound
    from tuckit.core.services.resolve import get_area_by_slug

    match = getattr(request, "resolver_match", None)
    if not match or match.url_name != "area":
        return {}
    org = current_org_or_fallback(request)
    if not org:
        return {}
    try:
        return {"capture_area": get_area_by_slug(org, match.kwargs["slug"])}
    except (NotFound, KeyError):
        # A 404-ing slug still renders the shell; falling back to Unfiled is
        # right, and raising here would turn a bad URL into a 500.
        return {}


def onboarding(request):
    """Expose onboarding state to every template so the floating Get-started
    widget renders on all pages — and make completion sticky so deleting an
    Area after finishing never resurrects the checklist."""
    from tuckit.core.services.onboarding import onboarding_state
    from tuckit.core.models import ActivityEvent

    org = current_org_or_fallback(request)
    if not org or org.onboarding_completed or org.onboarding_dismissed:
        return {}
    state = onboarding_state(org)
    if state.done and not org.onboarding_completed:
        org.onboarding_completed = True
        org.save(update_fields=["onboarding_completed"])
    show = not org.onboarding_dismissed and not org.onboarding_completed and not state.done
    baseline = (
        ActivityEvent.objects.filter(org=org).order_by("-id")
        .values_list("id", flat=True).first() or 0
    )
    # Is the user already looking at the slice the Plan/Bite steps link to? If
    # so the "Open the Slice →" button is a no-op that reloads the current page,
    # so the widget points at the field on this page instead. Computed here
    # rather than on OnboardingState, which is frozen and request-independent.
    match = getattr(request, "resolver_match", None)
    on_newest = bool(
        state.newest_slice_id
        and match
        and match.url_name == "slice"
        and str(match.kwargs.get("slice_id")) == str(state.newest_slice_id)
    )
    return {
        "onboarding": state,
        "onboarding_on_newest_slice": on_newest,
        "show_get_started": show,
        "onboarding_mcp_url": request.build_absolute_uri("/mcp"),
        "onboarding_agent_baseline": baseline,
    }


def live_cursor(request):
    """Starting activity cursor for the live poller (0 off-tenant). Prevents the
    poller from replaying pre-load events as toasts."""
    from tuckit.core.services.activity import latest_activity_id
    from tuckit.web.auth import current_org_or_fallback
    org = current_org_or_fallback(request)
    return {"live_cursor": latest_activity_id(org) if org else 0}
