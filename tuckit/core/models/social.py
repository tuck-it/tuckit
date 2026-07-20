from django.conf import settings
from django.db import models


class SocialAccount(models.Model):
    """A single external identity (provider + stable subject id) bound to a User.
    Login matches on (provider, uid) — never on email, which can change."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_accounts"
    )
    provider = models.CharField(max_length=32)  # "google" | "github"
    uid = models.CharField(max_length=255)  # provider's stable subject id
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("provider", "uid")

    def __str__(self):
        return f"{self.provider}:{self.uid} -> {self.user_id}"
