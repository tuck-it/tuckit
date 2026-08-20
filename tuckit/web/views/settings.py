import json

from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, HttpResponseForbidden
from django.urls import reverse
from django.views.decorators.http import require_POST

from tuckit.core.models import Invitation
from tuckit.core.services.exceptions import InvalidValue, LimitReached
from tuckit.core.services.invitations import cancel_invitation, create_invitation, send_invitation_email
from tuckit.core.services.mail import MailNotSent
from tuckit.core.services.oauth_apps import list_connected_apps, disconnect_app
from tuckit.core.services.orgs import is_org_admin
from tuckit.core.services.tokens import list_tokens, generate_token, revoke_token
from tuckit.web.views.settings_shell import settings_context


def org_agent(request):
    org = request.org
    ctx = settings_context(request, active="org_agent")
    ctx.update({"org": org, "tokens": list(list_tokens(org)),
                "mcp_url": request.build_absolute_uri("/mcp"),
                "connected_apps": list_connected_apps(org),
                "can_admin": is_org_admin(request.user, org)})
    return render(request, "web/settings/org_agent.html", ctx)


def org_shipped(request):
    org = request.org
    ctx = settings_context(request, active="org_shipped")
    ctx["org"] = org
    return render(request, "web/settings/org_shipped.html", ctx)


@require_POST
def token_create(request):
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
    token, raw = generate_token(org, request.POST.get("name") or "token")
    return render(request, "web/partials/_token_row.html", {"token": token, "raw": raw, "org": org})


@require_POST
def token_revoke(request, token_id):
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
    revoke_token(org, token_id)
    return HttpResponse(status=204)


@require_POST
def oauth_disconnect(request, client_id):
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
    disconnect_app(org, client_id)
    return render(request, "web/settings/_connected_apps.html",
                  {"connected_apps": list_connected_apps(org), "org": org})


@require_POST
def shipped_board_prefs(request):
    org = request.org
    if not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
    mode = request.POST.get("mode")
    if mode not in ("count", "days"):
        return HttpResponse("invalid mode", status=400)
    try:
        limit = int(request.POST.get("limit", ""))
    except (TypeError, ValueError):
        return HttpResponse("invalid limit", status=400)
    if not (1 <= limit <= 365):
        return HttpResponse("limit out of range", status=400)
    org.shipped_board_mode = mode
    org.shipped_board_limit = limit
    org.save(update_fields=["shipped_board_mode", "shipped_board_limit", "updated_at"])
    return HttpResponse(status=204)


@require_POST
def invite_create(request):
    org = request.org
    if org is None or not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
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
    inv.link = request.build_absolute_uri(reverse("web:invite_accept", args=[inv.token]))
    # The invitation stands either way — the link is the source of truth and
    # can be copied by hand. But whether the email went is not something the
    # inviter can find out any other way, so say it, both now (toast) and
    # afterwards (the row reads emailed_at).
    try:
        send_invitation_email(invitation=inv, link=inv.link)
        toast = {"message": f"Invited {inv.email} and emailed the link."}
    except MailNotSent as exc:
        toast = {
            "message": f"Invited {inv.email}, but the email did not go out. {exc} "
                       "Open Manage to copy the link and send it yourself.",
            "tone": "err",
        }
    resp = render(request, "web/partials/_invite_row.html", {"inv": inv, "org": org})
    resp["HX-Trigger"] = json.dumps({"tuckit:toast": toast})
    return resp


@require_POST
def invite_cancel(request, invitation_id):
    org = request.org
    if org is None or not is_org_admin(request.user, org):
        return HttpResponseForbidden("You don't have permission.")
    cancel_invitation(org=org, invitation_id=invitation_id)
    return HttpResponse(status=204)


def invite_manage(request, invitation_id):
    org = request.org
    inv = get_object_or_404(Invitation, id=invitation_id, org=org, accepted_at__isnull=True)
    inv.link = request.build_absolute_uri(reverse("web:invite_accept", args=[inv.token]))
    return render(request, "web/partials/_invite_manage_modal.html", {
        "inv": inv, "org": org, "can_admin": is_org_admin(request.user, org),
    })
