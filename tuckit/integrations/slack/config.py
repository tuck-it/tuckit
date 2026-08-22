from django.conf import settings


def slack_is_configured() -> bool:
    """Is this deployment able to talk to Slack at all?

    A deployment with no Slack app is perfectly ordinary, so the product must
    say "not configured" rather than mount half a feature. Same shape as
    mail.email_is_configured().
    """
    return bool(
        getattr(settings, "SLACK_CLIENT_ID", "")
        and getattr(settings, "SLACK_CLIENT_SECRET", "")
        and getattr(settings, "SLACK_SIGNING_SECRET", "")
    )


def interpretation_is_configured() -> bool:
    """Independent of slack_is_configured(): install and unfurling work without
    a model key, and only the mention handler needs one."""
    return bool(getattr(settings, "ANTHROPIC_API_KEY", ""))
