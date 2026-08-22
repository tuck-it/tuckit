from django.shortcuts import redirect

from tuckit.core.services.orgs import is_org_admin, is_org_owner
from tuckit.integrations.slack.config import slack_is_configured


def settings_context(request, *, active):
    """Shared context for the settings shell nav. request.org is set by
    TenantMiddleware — the settings IA is org-only now."""
    org = request.org
    return {
        "nav_org": org,
        "settings_active": active,
        "can_admin": is_org_admin(request.user, org) if org else False,
        "can_owner": is_org_owner(request.user, org) if org else False,
        # Gates the Slack nav entry. A deployment with no Slack app must show
        # nothing rather than a link into a half-configured feature.
        "slack_configured": slack_is_configured(),
    }


def settings_root(request):
    return redirect("web:settings_org_general", org_slug=request.org.slug)


def settings_account_root(request):
    return redirect("web:settings_account_profile", org_slug=request.org.slug)
