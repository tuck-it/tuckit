from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from tuckit.core.models import OrgMember
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.orgs import (
    create_org,
    leave_org,
    list_user_orgs,
    _owner_count,
)
from tuckit.web.auth import current_org_or_fallback
from tuckit.web.htmx import redirect_response
from tuckit.web.views.settings_shell import settings_context


def account_profile(request):
    ctx = settings_context(request, active="account_profile")
    return render(request, "web/settings/account_profile.html", ctx)


def account_orgs(request):
    current = current_org_or_fallback(request)
    orgs = list_user_orgs(request.user)
    for row in orgs:
        org = row["org"]
        sole_owner = row["role"] == "owner" and _owner_count(org) <= 1
        row["can_leave"] = not sole_owner and len(orgs) > 1
        row["is_current"] = bool(current) and current.id == org.id
    ctx = settings_context(request, active="account_orgs")
    ctx["orgs"] = orgs
    return render(request, "web/settings/account_orgs.html", ctx)


def _member_org(request, org_id):
    """Return the caller's OrgMember for org_id, or 404 if they aren't a member."""
    return get_object_or_404(OrgMember, org_id=org_id, user=request.user)


@require_POST
def org_create(request):
    try:
        org = create_org(request.user, name=request.POST.get("name", ""))
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    request.session["active_org_id"] = org.id
    return redirect_response(request, "web:home", org_slug=org.slug)


@require_POST
def org_leave(request, org_id):
    membership = _member_org(request, org_id)          # 404 if not a member
    org = membership.org
    try:
        leave_org(request.user, org=org)
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    if request.session.get("active_org_id") == org.id:
        request.session.pop("active_org_id", None)
    # `web:settings_account` no longer exists (this task removes it), and the
    # org just left may be the same org as the URL's org_slug — reversing back
    # into that org's settings would 404 under TenantMiddleware once org
    # membership is gone. web:root re-resolves a safe destination (remaining
    # org, or the org picker) via the same membership-checked fallback the
    # switcher uses.
    return redirect_response(request, "web:root")
