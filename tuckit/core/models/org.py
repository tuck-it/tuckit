from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

_SLUG_VALIDATOR = RegexValidator(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$", "invalid slug")

SHIPPED_BOARD_MODE_CHOICES = [("count", "Count"), ("days", "Days")]


class Org(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True, validators=[_SLUG_VALIDATOR])
    description = models.TextField(blank=True, default="")
    onboarding_dismissed = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)
    shipped_board_mode = models.CharField(
        max_length=5, choices=SHIPPED_BOARD_MODE_CHOICES, default="count"
    )
    shipped_board_limit = models.PositiveSmallIntegerField(default=8)
    next_slice_number = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class OrgMember(models.Model):
    ROLE_CHOICES = [("owner", "Owner"), ("admin", "Admin"), ("member", "Member")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships")
    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="members")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    created_at = models.DateTimeField(auto_now_add=True)
    # Watermark for Home's "since you were away" band. Null until the member's
    # first Home load: a first-ever visit must badge nothing, because every
    # event predates the member's involvement. Advanced on every Home render
    # AFTER the new-count has been computed — see mark_home_seen().
    home_seen_at = models.DateTimeField(null=True, blank=True)

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
