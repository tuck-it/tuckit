from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from tuckit.core.models import Invitation, OrgMember
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.orgs import (
    change_member_role,
    is_org_admin,
    is_org_owner,
    list_org_members,
    remove_member,
    rename_org,
)
from tuckit.web.auth import get_current_workspace


def org_settings(request):
    ws = get_current_workspace(request)
    org = ws.org if ws else None
    members = list(list_org_members(org)) if org else []
    workspaces = list(org.workspaces.order_by("name")) if org else []
    return render(request, "web/settings_org.html", {
        "workspace": ws,
        "org": org,
        "members": members,
        "workspaces": workspaces,
        "invitations": list(Invitation.objects.filter(org=org, accepted_at__isnull=True)) if org else [],
        "can_admin": bool(org and is_org_admin(request.user, org)),
        "can_owner": bool(org and is_org_owner(request.user, org)),
        "role_choices": OrgMember.ROLE_CHOICES,
    })


@require_POST
def org_rename(request):
    ws = get_current_workspace(request)
    if ws is None or not is_org_admin(request.user, ws.org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        org = rename_org(ws.org, request.POST.get("name", ""))
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    return HttpResponse(org.name)


def _member_in_current_org(request, member_id):
    """Fetch an OrgMember, 404 unless it belongs to the caller's current org."""
    ws = get_current_workspace(request)
    if ws is None:
        raise Http404
    return ws, get_object_or_404(OrgMember, id=member_id, org=ws.org)


@require_POST
def member_role(request, member_id):
    ws, member = _member_in_current_org(request, member_id)
    if not is_org_owner(request.user, ws.org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        change_member_role(ws.org, member=member, role=request.POST.get("role", ""))
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    return render(request, "web/partials/_member_row.html", {
        "m": member, "role_choices": OrgMember.ROLE_CHOICES,
        "can_owner": True, "can_admin": True,
    })


@require_POST
def member_remove(request, member_id):
    ws, member = _member_in_current_org(request, member_id)
    if not is_org_admin(request.user, ws.org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        remove_member(ws.org, member=member)
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    return HttpResponse(status=204)


@require_POST
def org_delete(request):
    ws = get_current_workspace(request)
    if ws is None or not is_org_owner(request.user, ws.org):
        return HttpResponseForbidden("권한이 없습니다")
    org = ws.org
    has_other = OrgMember.objects.filter(user=request.user).exclude(org=org).exists()
    if not has_other:
        return HttpResponse("마지막 조직은 삭제할 수 없습니다", status=400)
    request.session.pop("active_workspace_id", None)
    org.delete()  # cascades to workspaces/areas/slices/bites via FK on_delete=CASCADE
    return redirect("web:home")
