import json
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from tuckit.core.models import OAuthClient, OrgMember
from tuckit.core.services.oauth import (
    consume_authorization_code, create_authorization_code, create_client,
    issue_tokens, rotate_refresh_token, verify_pkce,
)
from tuckit.core.services.oauth_hook import TokenDenied, run_token_hook


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


def _redirect_error(redirect_uri: str, state: str, error: str):
    sep = "&" if "?" in redirect_uri else "?"
    url = f"{redirect_uri}{sep}error={error}"
    if state:
        url += f"&state={quote(state)}"
    return redirect(url)


def authorize(request):
    """OAuth 2.1 authorization endpoint. Login-required (LoginRequiredMiddleware).
    GET renders consent + org picker; POST ('Allow') issues an authorization code."""
    src = request.POST if request.method == "POST" else request.GET
    client_id = src.get("client_id", "")
    redirect_uri = src.get("redirect_uri", "")
    state = src.get("state", "")
    code_challenge = src.get("code_challenge", "")
    method = src.get("code_challenge_method", "")
    scope = src.get("scope", "")
    response_type = src.get("response_type", "code")

    client = OAuthClient.objects.filter(client_id=client_id).first()
    # Invalid client / redirect_uri -> render an error page, never redirect
    # (open-redirector guard: we only redirect to a verified redirect_uri).
    if client is None or redirect_uri not in client.redirect_uris:
        return render(request, "web/oauth/error.html",
                      {"detail": "Unknown client or redirect URI."}, status=400)
    if response_type != "code" or method != "S256" or not code_challenge:
        return _redirect_error(redirect_uri, state, "invalid_request")

    orgs = [m.org for m in OrgMember.objects.filter(user=request.user).select_related("org")]

    if request.method == "GET":
        return render(request, "web/oauth/consent.html", {
            "client": client, "orgs": orgs, "redirect_uri": redirect_uri,
            "state": state, "code_challenge": code_challenge,
            "code_challenge_method": method, "scope": scope,
            "response_type": response_type,
        })

    # POST = Allow
    org_id = request.POST.get("org_id", "")
    org = next((o for o in orgs if str(o.id) == str(org_id)), None)
    if org is None:
        return render(request, "web/oauth/error.html",
                      {"detail": "Select a workspace to authorize."}, status=400)
    raw_code = create_authorization_code(client, request.user, org, redirect_uri, code_challenge, scope)
    sep = "&" if "?" in redirect_uri else "?"
    url = f"{redirect_uri}{sep}code={raw_code}"
    if state:
        url += f"&state={quote(state)}"
    return redirect(url)


def _token_error(error: str, status: int):
    return JsonResponse({"error": error}, status=status)


@csrf_exempt
def token(request):
    """OAuth 2.1 token endpoint. Form-encoded; public clients (no secret)."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    grant = request.POST.get("grant_type", "")

    if grant == "authorization_code":
        code = request.POST.get("code", "")
        redirect_uri = request.POST.get("redirect_uri", "")
        client = OAuthClient.objects.filter(client_id=request.POST.get("client_id", "")).first()
        verifier = request.POST.get("code_verifier", "")
        if client is None:
            return _token_error("invalid_client", 401)
        rec = consume_authorization_code(code, client, redirect_uri)
        if rec is None or not verify_pkce(rec.code_challenge, verifier):
            return _token_error("invalid_grant", 400)
        try:
            run_token_hook(user=rec.user, org=rec.org, client=client)
        except TokenDenied:
            return _token_error("access_denied", 403)
        access, refresh, expires_in = issue_tokens(client, rec.user, rec.org, rec.scope)
        return JsonResponse({
            "access_token": access, "token_type": "Bearer",
            "expires_in": expires_in, "refresh_token": refresh, "scope": rec.scope,
        })

    if grant == "refresh_token":
        rotated = rotate_refresh_token(request.POST.get("refresh_token", ""))
        if rotated is None:
            return _token_error("invalid_grant", 400)
        access, refresh, expires_in, scope = rotated
        return JsonResponse({
            "access_token": access, "token_type": "Bearer",
            "expires_in": expires_in, "refresh_token": refresh, "scope": scope,
        })

    return _token_error("unsupported_grant_type", 400)
