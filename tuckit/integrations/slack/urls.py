from django.urls import path

from tuckit.integrations.slack import views
from tuckit.integrations.slack.config import slack_is_configured


def slack_settings_urlpatterns() -> list:
    """The org-scoped half of the same rule: no credentials, no URLs.

    These four were mounted unconditionally at first, and that was the same
    half-existing feature the docstring below refuses. With Slack
    unconfigured, /<org>/settings/slack still rendered a live "Connect to
    Slack" button, and pressing it (or reaching slack_install_begin any other
    way) raised NoReverseMatch on web:slack_install_callback, which is a 500.
    The nav entry is hidden in that state, so the only way in is a typed or
    bookmarked URL, which is exactly the path nobody watches.

    They live here rather than in tuckit/web/urls.py so the gate is one
    decision in one file. They carry the org slug, so unlike slack_urlpatterns
    they belong inside the tenant-scoped settings patterns.
    """
    if not slack_is_configured():
        return []
    return [
        path("<slug:org_slug>/settings/slack", views.settings_slack, name="settings_slack"),
        path("<slug:org_slug>/settings/slack/connect", views.slack_install_begin,
             name="slack_install_begin"),
        path("<slug:org_slug>/settings/slack/confirm", views.slack_install_confirm,
             name="slack_install_confirm"),
        path("<slug:org_slug>/settings/slack/disconnect", views.slack_disconnect,
             name="slack_disconnect"),
    ]


def slack_urlpatterns() -> list:
    """No credentials, no URLs. The feature does not half-exist."""
    if not slack_is_configured():
        return []
    return [
        path("slack/events", views.slack_events, name="slack_events"),
        path("slack/oauth/callback", views.slack_install_callback, name="slack_install_callback"),
        path("slack/connect", views.slack_connect_begin, name="slack_connect_begin"),
        path("slack/connect/done", views.slack_connect_callback, name="slack_connect_callback"),
        path("slack/command", views.slack_command, name="slack_command"),
    ]
