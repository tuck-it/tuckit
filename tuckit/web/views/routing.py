from django.http import JsonResponse

from tuckit.core.models import Org, Workspace
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slugs import normalize_slug, validate_slug


def check_slug(request):
    kind = request.GET.get("kind", "org")
    if kind not in ("org", "workspace"):
        return JsonResponse({"available": False, "error": "알 수 없는 종류"})
    try:
        slug = validate_slug(request.GET.get("slug", ""), kind=kind)
    except InvalidValue as exc:
        return JsonResponse({"available": False, "error": str(exc)})
    if kind == "org":
        taken = Org.objects.filter(slug=slug).exists()
    else:
        org = Org.objects.filter(slug=normalize_slug(request.GET.get("org", ""))).first()
        if not org:
            return JsonResponse({"available": False, "error": "조직을 찾을 수 없습니다"})
        taken = Workspace.objects.filter(org=org, slug=slug).exists()
    if taken:
        return JsonResponse({"available": False, "error": "이미 사용 중입니다"})
    return JsonResponse({"available": True, "error": None})


from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from tuckit.core.models import OrgMember
from tuckit.core.services.orgs import accessible_workspaces


@login_required
def root_redirect(request):
    ws_id = request.session.get("active_workspace_id")
    ws = None
    if ws_id:
        ws = Workspace.objects.filter(pk=ws_id).select_related("org").first()
        if ws and not OrgMember.objects.filter(user=request.user, org=ws.org).exists():
            ws = None
    if ws is None:
        ws = accessible_workspaces(request.user).select_related("org").first()
    if ws is None:
        return redirect("web:welcome")
    return redirect("web:home", org_slug=ws.org.slug, ws_slug=ws.slug)
