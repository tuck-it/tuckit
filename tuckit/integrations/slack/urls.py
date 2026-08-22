from django.urls import path

from tuckit.integrations.slack import views
from tuckit.integrations.slack.config import slack_is_configured


def slack_urlpatterns() -> list:
    """No credentials, no URLs. The feature does not half-exist."""
    if not slack_is_configured():
        return []
    return [
        path("slack/events", views.slack_events, name="slack_events"),
        path("slack/oauth/callback", views.slack_install_callback, name="slack_install_callback"),
    ]
