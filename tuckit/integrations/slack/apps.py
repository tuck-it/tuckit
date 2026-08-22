from django.apps import AppConfig


class SlackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tuckit.integrations.slack"
    label = "slack"

    def ready(self):
        from tuckit.integrations.slack import handlers  # noqa: F401  (registers the jobs)
