from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from tuckit.core.models import OrgMember, Workspace
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.orgs import (
    create_org,
    is_org_owner,
    leave_org,
    list_user_orgs,
    _owner_count,
)
from tuckit.web.auth import get_current_workspace
from tuckit.web.htmx import redirect_response


def account_settings(request):
    ws = get_current_workspace(request)
    orgs = list_user_orgs(request.user) if request.user.is_authenticated else []
    # annotate each row with whether 나가기 is allowed, so the template can hide it
    for row in orgs:
        org = row["org"]
        sole_owner = row["role"] == "owner" and _owner_count(org) <= 1
        row["can_leave"] = not sole_owner and len(orgs) > 1
        row["is_current"] = bool(ws) and ws.org_id == org.id
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
    return redirect_response(request, "web:home")


@require_POST
def org_leave(request, org_id):
    membership = _member_org(request, org_id)          # 404 if not a member
    org = membership.org
    try:
        leave_org(request.user, org=org)
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    ws = get_current_workspace(request)
    if ws is None or ws.org_id == org.id:
        request.session.pop("active_workspace_id", None)
    return redirect_response(request, "web:settings_account")


@require_POST
def switch_org(request, org_id):
    membership = _member_org(request, org_id)          # 404 if not a member
    first_ws = Workspace.objects.filter(org=membership.org).order_by("name").first()
    if first_ws is not None:
        request.session["active_workspace_id"] = first_ws.id
    return redirect_response(request, "web:home")
