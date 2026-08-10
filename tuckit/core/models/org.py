from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

_SLUG_VALIDATOR = RegexValidator(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$", "invalid slug")
_KEY_VALIDATOR = RegexValidator(r"^[A-Z][A-Z0-9]{1,5}$", "invalid key")

SHIPPED_BOARD_MODE_CHOICES = [("count", "Count"), ("days", "Days")]


class Org(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True, validators=[_SLUG_VALIDATOR])
    # The human-facing prefix in a ref: the 'TUC' of 'TUC-47'. Lives on Org
    # rather than Area because numbers are minted per-org (next_slice_number
    # below) and an Inbox Ticket has no area at all — an area-scoped key would
    # leave the entire Inbox unnamable.
    key = models.CharField(max_length=6, unique=True, validators=[_KEY_VALIDATOR])
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

    def save(self, *args, **kwargs):
        # Filled here rather than in create_org() because Org.objects.create()
        # is called directly in bootstrap, migrations and many tests; a blank
        # key would collide with every other blank one on the unique index.
        if self._state.adding and not self.key:
            from django.db import IntegrityError, transaction

            from tuckit.core.services.keys import derive_key, unique_key

            base = derive_key(self.slug)
            attempts = 5
            for attempt in range(attempts):
                self.key = unique_key(base, Org.objects.values_list("key", flat=True))
                try:
                    # atomic() confines a failed INSERT to its own savepoint —
                    # the same reasoning set_org_key uses: on Postgres an
                    # uncaught IntegrityError poisons the whole surrounding
                    # transaction (e.g. create_org()'s), not just this INSERT.
                    with transaction.atomic():
                        super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    # unique_key()'s read of "taken" keys and this INSERT are
                    # not atomic, so two concurrent signups can both compute
                    # the same free-looking key (e.g. "acme-corp" and
                    # "acme-inc" both deriving "AC") and only one INSERT wins.
                    # Re-derive against fresh state and retry rather than
                    # letting the race surface as a 500; bounded so a
                    # genuinely broken unique index still fails loudly
                    # instead of looping forever.
                    if attempt == attempts - 1:
                        raise
            return  # unreachable: the loop always returns or raises above
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ActiveOrgMemberManager(models.Manager):
    """Excludes ended memberships, so forgetting to filter is the safe mistake.

    This model gates every page (TenantMiddleware), the org switcher and the
    OAuth consent screen. With an opt-in .active() the cost of overlooking one
    of those call sites — or adding a new one next year — is an authorization
    bypass, so the filter is the default and reaching past it has to be typed
    out as all_objects.
    """

    def get_queryset(self):
        return super().get_queryset().filter(ended_at__isnull=True)


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
    # A membership is a period, not a row that gets destroyed: null while it is
    # live, stamped when the member leaves or is removed. It is deliberately not
    # named deleted_at — the row is a standing historical fact ("was a member
    # from created_at to ended_at"), and that is what makes it safe for
    # Slice.created_by and the activity log to point at.
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = ActiveOrgMemberManager()
    all_objects = models.Manager()

    class Meta:
        # Kept as-is on purpose: an ended row still occupies the slot, which is
        # what forces a rejoin to resurrect this membership instead of opening a
        # second one. That is what keeps one person's history a single thread.
        unique_together = [("user", "org")]
        # Forward FK access (slice.created_by, slice.assignee) goes through the
        # base manager, so an ended membership still resolves and history keeps
        # its name. The gate is filtered; the record is not.
        base_manager_name = "all_objects"

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def __str__(self):
        suffix = "" if self.ended_at is None else " — ended"
        return f"{self.user} @ {self.org} ({self.role}){suffix}"


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
