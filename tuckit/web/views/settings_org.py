from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
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
from tuckit.web.views.settings_shell import settings_context


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


def member_manage(request, member_id):
    member = _member_in_org(request, member_id)
    return render(request, "web/partials/_member_manage_modal.html", {
        "m": member,
        "org": request.org,
        "role_choices": OrgMember.ROLE_CHOICES,
        "can_owner": is_org_owner(request.user, request.org),
        "can_admin": is_org_admin(request.user, request.org),
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


def org_home(request):
    """First-class org landing at /<org_slug>/. request.org is set by
    TenantMiddleware (404 for non-members); request.workspace stays None."""
    org = request.org
    return render(request, "web/org_home.html", {
        "workspace": request.workspace,
        "org": org,
        "workspaces": list(org.workspaces.order_by("name")),
        "can_admin": is_org_admin(request.user, org),
        "can_owner": is_org_owner(request.user, org),
    })


def org_general(request):
    org = request.org
    ctx = settings_context(request, active="org_general")
    ctx["org"] = org
    return render(request, "web/settings/org_general.html", ctx)


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


def org_members(request):
    org = request.org
    members = list(list_org_members(org))
    invitations = list(Invitation.objects.filter(org=org, accepted_at__isnull=True))
    for inv in invitations:
        inv.link = request.build_absolute_uri(reverse("web:invite_accept", args=[inv.token]))
    ctx = settings_context(request, active="org_members")
    ctx.update({"org": org, "members": members, "invitations": invitations,
                "role_choices": OrgMember.ROLE_CHOICES})
    return render(request, "web/settings/org_members.html", ctx)


def org_workspaces(request):
    org = request.org
    ctx = settings_context(request, active="org_workspaces")
    ctx.update({"org": org, "workspaces": list(org.workspaces.order_by("name"))})
    return render(request, "web/settings/org_workspaces.html", ctx)


def org_danger(request):
    ctx = settings_context(request, active="org_danger")
    ctx["org"] = request.org
    return render(request, "web/settings/org_danger.html", ctx)
