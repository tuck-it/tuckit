from django.conf import settings
from django.utils.module_loading import import_string


def run_signup_hook(*, user, org) -> None:
    """Call the configured post-signup hook if any (cloud attaches billing here)."""
    path = getattr(settings, "TUCKIT_SIGNUP_HOOK", None)
    if not path:
        return
    import_string(path)(user=user, org=org)
