import hashlib
import secrets

from django.utils import timezone

from tuckit.core.models import ApiToken, Org


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token(org: Org, name: str) -> tuple[ApiToken, str]:
    """Takes an Org directly now that the agent-settings page is org-level and
    ApiToken has always been org-scoped (see task-5-report.md Option B fix)."""
    raw = secrets.token_urlsafe(32)
    token = ApiToken.objects.create(org=org, name=name, token_hash=hash_token(raw))
    return token, raw


def list_tokens(org: Org):
    return ApiToken.objects.filter(org=org).order_by("-created_at")


def revoke_token(org: Org, token_id: int) -> None:
    ApiToken.objects.filter(org=org, pk=token_id).delete()


def resolve_org_token(raw: str) -> ApiToken | None:
    """The ApiToken behind a bearer string, or None. Callers that only need the
    tenant use resolve_org; callers that must identify the connection (the rate
    limiter) need the row itself."""
    try:
        token = ApiToken.objects.select_related("org").get(token_hash=hash_token(raw))
    except ApiToken.DoesNotExist:
        return None
    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at"])
    return token


def resolve_org(raw: str) -> Org | None:
    """Authoritative bearer-token -> tenant resolution for the MCP wire
    protocol. Returns the Org, the tenant boundary the tools operate against."""
    token = resolve_org_token(raw)
    return token.org if token is not None else None
