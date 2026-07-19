import json

from django.conf import settings
from django.http import HttpResponseNotAllowed, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from tuckit.core.services.oauth import create_client


def issuer(request) -> str:
    if settings.TUCKIT_OAUTH_ISSUER:
        return settings.TUCKIT_OAUTH_ISSUER.rstrip("/")
    return request.build_absolute_uri("/").rstrip("/")


def protected_resource_metadata(request):
    """RFC 9728 Protected Resource Metadata for the /mcp resource."""
    iss = issuer(request)
    return JsonResponse({
        "resource": f"{iss}/mcp",
        "authorization_servers": [iss],
        "bearer_methods_supported": ["header"],
    })


def authorization_server_metadata(request):
    """RFC 8414 Authorization Server Metadata."""
    iss = issuer(request)
    return JsonResponse({
        "issuer": iss,
        "authorization_endpoint": f"{iss}/oauth/authorize",
        "token_endpoint": f"{iss}/oauth/token",
        "registration_endpoint": f"{iss}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


@csrf_exempt
def register(request):
    """RFC 7591 Dynamic Client Registration for public clients."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not settings.TUCKIT_OAUTH_DCR_OPEN:
        return JsonResponse({"error": "registration_not_supported"}, status=403)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "invalid_client_metadata"}, status=400)
    redirect_uris = data.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return JsonResponse({"error": "invalid_redirect_uri"}, status=400)
    client = create_client(name=data.get("client_name", ""), redirect_uris=redirect_uris)
    return JsonResponse({
        "client_id": client.client_id,
        "client_name": client.name,
        "redirect_uris": client.redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }, status=201)
