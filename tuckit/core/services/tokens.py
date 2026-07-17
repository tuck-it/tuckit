import hashlib
import secrets

from django.utils import timezone

from tuckit.core.models import ApiToken, Org, Workspace


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token(workspace: Workspace, name: str) -> tuple[ApiToken, str]:
    """Takes a Workspace (every call site already has one on hand) but writes
    and reads are org-scoped now that ApiToken.workspace is nullable — the org
    is the real tenant boundary (see task-5-report.md Option B fix)."""
    raw = secrets.token_urlsafe(32)
    token = ApiToken.objects.create(org=workspace.org, name=name, token_hash=hash_token(raw))
    return token, raw


def list_tokens(workspace: Workspace):
    return ApiToken.objects.filter(org=workspace.org).order_by("-created_at")


def revoke_token(workspace: Workspace, token_id: int) -> None:
    ApiToken.objects.filter(org=workspace.org, pk=token_id).delete()


def resolve_org(raw: str) -> Org | None:
    """Authoritative bearer-token -> tenant resolution for the MCP wire
    protocol. Returns the Org (not the Workspace) now that Org is the tenant
    boundary the tools operate against."""
    try:
        token = ApiToken.objects.select_related("org").get(token_hash=hash_token(raw))
    except ApiToken.DoesNotExist:
        return None
    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at"])
    return token.org
