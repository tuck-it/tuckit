from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from tuckit.core.models.org import Org

_SLUG_VALIDATOR = RegexValidator(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$", "invalid slug")

SHIPPED_BOARD_MODE_CHOICES = [("count", "Count"), ("days", "Days")]


class Workspace(models.Model):
    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="workspaces")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, validators=[_SLUG_VALIDATOR])
    description = models.TextField(blank=True, default="")
    onboarding_dismissed = models.BooleanField(default=False)
    shipped_board_mode = models.CharField(
        max_length=5, choices=SHIPPED_BOARD_MODE_CHOICES, default="count"
    )
    shipped_board_limit = models.PositiveSmallIntegerField(default=8)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("org", "slug")]
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "org", name="uniq_ws_name_per_org"
            ),
        ]

    def __str__(self):
        return self.name


class ApiToken(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="tokens")
    name = models.CharField(max_length=200)
    token_hash = models.CharField(max_length=64, unique=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.workspace.slug})"
