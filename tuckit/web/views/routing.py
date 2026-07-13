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
        taken = bool(org and Workspace.objects.filter(org=org, slug=slug).exists())
    if taken:
        return JsonResponse({"available": False, "error": "이미 사용 중입니다"})
    return JsonResponse({"available": True, "error": None})
