from django.conf import settings
from django.contrib.auth import authenticate, login
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from tuckit.core.models import User
from tuckit.core.services.accounts import create_account
from tuckit.core.services.exceptions import InvalidValue, NotFound
from tuckit.core.services.invitations import accept_invitation, get_pending_invitation, register_invited
from tuckit.web.auth import landing_route


def _safe_next(request):
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return ""


def _success(request):
    nxt = _safe_next(request)
    if nxt:
        return redirect(nxt)
    name, kwargs = landing_route(request)
    return redirect(name, **kwargs)


def _render(request, step, ctx, error=None):
    from tuckit.core.services.social import enabled_providers

    data = {"step": step, "next": _safe_next(request), **ctx}
    if step == "email":
        data["social_providers"] = enabled_providers()
    if error:
        data["error"] = error
    return render(request, "registration/login.html", data)


def auth_entry(request):
    """Email-first unified login/sign-up. One URL, server-rendered steps keyed off
    the hidden `step` field; email is re-sent each step (no wizard session state)."""
    if request.method != "POST":
        return _render(request, "email", {})

    step = request.POST.get("step", "identify")
    email = (request.POST.get("email") or "").strip()

    if step == "identify":
        if not email:
            return _render(request, "email", {"email": email}, "Please enter your email.")
        if User.objects.filter(email=email).exists():
            return _render(request, "password", {"email": email})
        if not settings.REGISTRATION_OPEN:
            return _render(request, "email", {"email": email}, "No account found.")
        return _render(request, "set_password", {"email": email})

    if step == "login":
        user = authenticate(request, username=email, password=request.POST.get("password", ""))
        if user is None:
            return _render(request, "password", {"email": email}, "Incorrect password.")
        login(request, user)
        return _success(request)

    if step == "register":
        if not settings.REGISTRATION_OPEN:
            return _render(request, "email", {"email": email}, "No account found.")
        try:
            user = create_account(email=email, password=request.POST.get("password", ""))
        except InvalidValue as exc:
            return _render(request, "set_password", {"email": email}, str(exc))
        login(request, user)
        return _success(request)

    return _render(request, "email", {})


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
            return redirect("web:root")
        # anonymous: create the invited user (email locked) and join
        try:
            user, _member = register_invited(invitation=invitation, password=request.POST.get("password", ""))
        except (InvalidValue, NotFound) as exc:
            return render(request, "registration/invite_accept.html", {"invitation": invitation, "error": str(exc)})
        login(request, user)
        return redirect("web:root")

    return render(request, "registration/invite_accept.html", {"invitation": invitation})
