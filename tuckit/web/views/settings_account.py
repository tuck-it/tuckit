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


def account_settings(request):
    # /settings/account is non-tenant (no request.workspace); use the chrome
    # fallback workspace only to annotate which org is "current".
    ws = (
        accessible_workspaces(request.user).select_related("org").first()
        if request.user.is_authenticated
        else None
    )
    orgs = list_user_orgs(request.user) if request.user.is_authenticated else []
    # annotate each row with whether 나가기 is allowed, so the template can hide it
    for row in orgs:
        org = row["org"]
        sole_owner = row["role"] == "owner" and _owner_count(org) <= 1
        row["can_leave"] = not sole_owner and len(orgs) > 1
        row["is_current"] = bool(ws) and ws.org_id == org.id
        row["first_workspace"] = Workspace.objects.filter(org=org).order_by("name").first()
    return render(request, "web/settings_account.html", {
        "workspace": ws,
        "org": ws.org if ws else None,
        "orgs": orgs,
    })


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
    return redirect_response(request, "web:settings_account")
