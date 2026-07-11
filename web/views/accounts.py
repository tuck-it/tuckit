from django.conf import settings
from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect, render

from core.services.accounts import register
from core.services.exceptions import InvalidValue, NotFound
from core.services.invitations import accept_invitation, get_pending_invitation, register_invited


def register_view(request):
    if not settings.REGISTRATION_OPEN:
        raise Http404
    if request.method == "POST":
        try:
            user, _org, _ws = register(
                email=request.POST.get("email", ""),
                org_name=request.POST.get("org_name", ""),
                slug=request.POST.get("slug", ""),
                password=request.POST.get("password", ""),
            )
        except InvalidValue as exc:
            return render(request, "registration/register.html", {"error": str(exc), "values": request.POST})
        login(request, user)
        return redirect("web:home")
    return render(request, "registration/register.html", {"values": {}})


def invite_accept(request, token):
    try:
        invitation = get_pending_invitation(token)
    except NotFound:
        return render(request, "registration/invite_accept.html", {"invalid": True})

    if request.method == "POST":
        if request.user.is_authenticated:
            try:
                accept_invitation(token=token, user=request.user)
            except (InvalidValue, NotFound) as exc:
                return render(request, "registration/invite_accept.html", {"invitation": invitation, "error": str(exc)})
            return redirect("web:home")
        # anonymous: create the invited user (email locked) and join
        try:
            user, _member = register_invited(invitation=invitation, password=request.POST.get("password", ""))
        except (InvalidValue, NotFound) as exc:
            return render(request, "registration/invite_accept.html", {"invitation": invitation, "error": str(exc)})
        login(request, user)
        return redirect("web:home")

    return render(request, "registration/invite_accept.html", {"invitation": invitation})
