from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
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
from tuckit.web.htmx import redirect_response


def org_settings(request):
    org = request.org
    members = list(list_org_members(org))
    workspaces = list(org.workspaces.order_by("name"))
    return render(request, "web/settings_org.html", {
        "workspace": request.workspace,
        "org": org,
        "members": members,
        "workspaces": workspaces,
        "invitations": list(Invitation.objects.filter(org=org, accepted_at__isnull=True)),
        "can_admin": is_org_admin(request.user, org),
        "can_owner": is_org_owner(request.user, org),
        "role_choices": OrgMember.ROLE_CHOICES,
    })


@require_POST
def org_rename(request):
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        org = rename_org(org, request.POST.get("name", ""))
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    return HttpResponse(org.name)


def _member_in_org(request, member_id):
    return get_object_or_404(OrgMember, id=member_id, org=request.org)


@require_POST
def member_role(request, member_id):
    member = _member_in_org(request, member_id)
    if not is_org_owner(request.user, request.org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        change_member_role(request.org, member=member, role=request.POST.get("role", ""))
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    return render(request, "web/partials/_member_row.html", {
        "m": member, "role_choices": OrgMember.ROLE_CHOICES,
        "can_owner": True, "can_admin": True, "org": request.org,
    })


@require_POST
def member_remove(request, member_id):
    member = _member_in_org(request, member_id)
    if not is_org_admin(request.user, request.org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        remove_member(request.org, member=member)
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    return HttpResponse(status=204)


@require_POST
def org_delete(request):
    org = request.org
    if not is_org_owner(request.user, org):
        return HttpResponseForbidden("권한이 없습니다")
    has_other = OrgMember.objects.filter(user=request.user).exclude(org=org).exists()
    if not has_other:
        return HttpResponse("마지막 조직은 삭제할 수 없습니다", status=400)
    request.session.pop("active_workspace_id", None)
    org.delete()  # cascades to workspaces/areas/slices/bites via FK on_delete=CASCADE
    return redirect_response(request, "web:root")
