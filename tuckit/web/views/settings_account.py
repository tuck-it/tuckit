from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from tuckit.core.models import OrgMember, Workspace
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.orgs import (
    accessible_workspaces,
    create_org,
    leave_org,
    list_user_orgs,
    _owner_count,
)
from tuckit.web.htmx import redirect_response
from tuckit.web.views.settings_shell import settings_context


def account_profile(request):
    ctx = settings_context(request, active="account_profile")
    return render(request, "web/settings/account_profile.html", ctx)


def account_orgs(request):
    ws = (accessible_workspaces(request.user).select_related("org").first()
          if request.user.is_authenticated else None)
    orgs = list_user_orgs(request.user)
    for row in orgs:
        org = row["org"]
        sole_owner = row["role"] == "owner" and _owner_count(org) <= 1
        row["can_leave"] = not sole_owner and len(orgs) > 1
        row["is_current"] = bool(ws) and ws.org_id == org.id
        row["can_create_ws"] = row["role"] in ("owner", "admin")
    ctx = settings_context(request, active="account_orgs")
    ctx["orgs"] = orgs
    return render(request, "web/settings/account_orgs.html", ctx)


def _member_org(request, org_id):
    """Return the caller's OrgMember for org_id, or 404 if they aren't a member."""
    return get_object_or_404(OrgMember, org_id=org_id, user=request.user)


@require_POST
def org_create(request):
    try:
        org, ws = create_org(request.user, name=request.POST.get("name", ""))
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    request.session["active_workspace_id"] = ws.id
    return redirect_response(request, "web:home", org_slug=org.slug, ws_slug=ws.slug)


@require_POST
def org_leave(request, org_id):
    membership = _member_org(request, org_id)          # 404 if not a member
    org = membership.org
    try:
        leave_org(request.user, org=org)
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    active_id = request.session.get("active_workspace_id")
    if active_id is None or Workspace.objects.filter(pk=active_id, org=org).exists():
        request.session.pop("active_workspace_id", None)
    # `web:settings_account` no longer exists (this task removes it), and the
    # org just left may be the same org as the URL's org_slug — reversing back
    # into that org's settings would 404 under TenantMiddleware once org
    # membership is gone. web:root re-resolves a safe destination (remaining
    # workspace, or first-org) via the same membership-checked fallback the
    # workspace switcher uses.
    return redirect_response(request, "web:root")
