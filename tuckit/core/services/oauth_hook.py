from django.conf import settings
from django.utils.module_loading import import_string


class TokenDenied(Exception):
    """Raised by a token hook to refuse issuance (e.g. plan limit reached)."""


def run_token_hook(*, user, org, client) -> None:
    dotted = getattr(settings, "TUCKIT_OAUTH_TOKEN_HOOK", None)
    if not dotted:
        return
    hook = import_string(dotted)
    hook(user=user, org=org, client=client)
