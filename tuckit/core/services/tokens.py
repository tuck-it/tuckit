import hashlib
import secrets

from django.utils import timezone

from tuckit.core.models import ApiToken, Workspace


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token(workspace: Workspace, name: str) -> tuple[ApiToken, str]:
    raw = secrets.token_urlsafe(32)
    token = ApiToken.objects.create(
        workspace=workspace, name=name, token_hash=hash_token(raw)
    )
    return token, raw


def list_tokens(workspace: Workspace):
    return ApiToken.objects.filter(workspace=workspace).order_by("-created_at")


def revoke_token(workspace: Workspace, token_id: int) -> None:
    ApiToken.objects.filter(workspace=workspace, pk=token_id).delete()


def resolve_workspace(raw: str) -> Workspace | None:
    try:
        token = ApiToken.objects.select_related("workspace").get(token_hash=hash_token(raw))
    except ApiToken.DoesNotExist:
        return None
    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at"])
    return token.workspace
