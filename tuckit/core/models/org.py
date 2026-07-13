from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

_SLUG_VALIDATOR = RegexValidator(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$", "invalid slug")


class Org(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True, validators=[_SLUG_VALIDATOR])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class OrgMember(models.Model):
    ROLE_CHOICES = [("owner", "Owner"), ("admin", "Admin"), ("member", "Member")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships")
    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="members")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "org")]

    def __str__(self):
        return f"{self.user} @ {self.org} ({self.role})"


class Invitation(models.Model):
    ROLE_CHOICES = [("admin", "Admin"), ("member", "Member")]

    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    token = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="sent_invitations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"invite {self.email} -> {self.org}"
