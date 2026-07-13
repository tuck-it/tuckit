from django.shortcuts import redirect, render
from django.http import HttpResponse, HttpResponseForbidden
from django.urls import reverse
from django.views.decorators.http import require_POST

from tuckit.core.services.exceptions import InvalidValue, LimitReached
from tuckit.core.services.invitations import cancel_invitation, create_invitation, send_invitation_email
from tuckit.core.services.orgs import delete_workspace, is_org_admin, rename_workspace
from tuckit.core.services.tokens import list_tokens, generate_token, revoke_token
from tuckit.web.auth import get_current_workspace
from tuckit.web.htmx import redirect_response


def settings(request):
    ws = get_current_workspace(request)
    return redirect("web:settings_workspace", org_slug=ws.org.slug, ws_slug=ws.slug)


def workspace_settings(request):
    ws = get_current_workspace(request)
    return render(request, "web/settings_workspace.html", {
        "workspace": ws,
        "org": ws.org if ws else None,
        "tokens": list(list_tokens(ws)) if ws else [],
        "mcp_url": request.build_absolute_uri("/mcp"),
        "can_admin": bool(ws and is_org_admin(request.user, ws.org)),
    })


def token_create(request):
    ws = get_current_workspace(request)
    token, raw = generate_token(ws, request.POST.get("name") or "token")
    return render(request, "web/partials/_token_row.html", {"token": token, "raw": raw})


def token_revoke(request, token_id):
    ws = get_current_workspace(request)
    revoke_token(ws, token_id)
    return HttpResponse(status=204)


def workspace_rename(request):
    ws = get_current_workspace(request)
    try:
        ws = rename_workspace(ws, request.POST.get("name", ""))
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    return HttpResponse(ws.name)


@require_POST
def workspace_delete(request):
    ws = get_current_workspace(request)
    if ws is None or not is_org_admin(request.user, ws.org):
        return HttpResponseForbidden("권한이 없습니다")
    ws_id = ws.id
    try:
        delete_workspace(ws)
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    if request.session.get("active_workspace_id") == ws_id:
        request.session.pop("active_workspace_id", None)
    return redirect_response(request, "web:root")


@require_POST
def invite_create(request):
    org = request.org
    if org is None or not is_org_admin(request.user, org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        inv = create_invitation(
            org=org,
            email=request.POST.get("email", ""),
            role=request.POST.get("role", "member"),
            invited_by=request.user,
        )
    except LimitReached as exc:
        return HttpResponse(str(exc), status=402)
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    link = request.build_absolute_uri(reverse("web:invite_accept", args=[inv.token]))
    send_invitation_email(invitation=inv, link=link)  # optional; link below is the source of truth
    return render(request, "web/partials/_invite_row.html", {"inv": inv, "link": link, "org": org})


@require_POST
def invite_cancel(request, invitation_id):
    org = request.org
    if org is None or not is_org_admin(request.user, org):
        return HttpResponseForbidden("권한이 없습니다")
    cancel_invitation(org=org, invitation_id=invitation_id)
    return HttpResponse(status=204)
