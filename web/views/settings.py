from django.shortcuts import render
from django.http import HttpResponse, HttpResponseForbidden

from core.models import Invitation
from core.services.exceptions import InvalidValue
from core.services.invitations import cancel_invitation, create_invitation, send_invitation_email
from core.services.orgs import is_org_admin
from core.services.tokens import list_tokens, generate_token, revoke_token
from web.auth import get_current_workspace


def settings(request):
    ws = get_current_workspace(request)
    return render(request, "web/settings.html", {
        "workspace": ws,
        "tokens": list(list_tokens(ws)),
        "mcp_url": request.build_absolute_uri("/mcp"),
        "invitations": list(Invitation.objects.filter(org=ws.org, accepted_at__isnull=True)) if ws else [],
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
    ws.name = request.POST["name"]
    ws.save(update_fields=["name", "updated_at"])
    return HttpResponse(ws.name)


def invite_create(request):
    ws = get_current_workspace(request)
    if ws is None or not is_org_admin(request.user, ws.org):
        return HttpResponseForbidden("권한이 없습니다")
    try:
        inv = create_invitation(
            org=ws.org,
            email=request.POST.get("email", ""),
            role=request.POST.get("role", "member"),
            invited_by=request.user,
        )
    except InvalidValue as exc:
        return HttpResponse(str(exc), status=400)
    link = request.build_absolute_uri(f"/invite/{inv.token}/")
    send_invitation_email(invitation=inv, link=link)  # optional; link below is the source of truth
    return render(request, "web/partials/_invite_row.html", {"inv": inv, "link": link})


def invite_cancel(request, invitation_id):
    ws = get_current_workspace(request)
    if ws is None or not is_org_admin(request.user, ws.org):
        return HttpResponseForbidden("권한이 없습니다")
    cancel_invitation(org=ws.org, invitation_id=invitation_id)
    return HttpResponse(status=204)
