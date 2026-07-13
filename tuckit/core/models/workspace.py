from django.db import models

from tuckit.core.models.org import Org


class Workspace(models.Model):
    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="workspaces")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True, default="")
    onboarding_dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("org", "slug")]

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
