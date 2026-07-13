from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.orgs import create_workspace, is_org_admin


@login_required
@require_POST
def workspace_create(request):
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        ws = create_workspace(org, request.POST.get("name") or "Workspace")
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    request.session["active_workspace_id"] = ws.id
    return redirect("web:home", org_slug=org.slug, ws_slug=ws.slug)
