from django.db import models


class Tag(models.Model):
    org = models.ForeignKey("core.Org", on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = [("org", "name")]

    def __str__(self):
        return f"#{self.name}"


class Area(models.Model):
    org = models.ForeignKey("core.Org", on_delete=models.CASCADE, related_name="areas")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True, default="")
    archived = models.BooleanField(default=False)
    rank = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("org", "slug")]
        ordering = ["rank"]

    def __str__(self):
        return self.name


class Slice(models.Model):
    # status는 사람이 내리는 결정만 담는다 — 진행도는 slice_stage()가 산출물에서
    # 파생한다. 'building'은 관찰이라 stage의 'executing'과 겹쳤고, 자동으로
    # 켜지지 않아 아무도 켜지 않았다(A0, 2026-07-27: 전 org 0건).
    STATUS_CHOICES = [
        ("open", "Open"),
        ("shipped", "Shipped"),
        ("dropped", "Dropped"),
    ]
    SOURCE_CHOICES = [("human", "Human"), ("agent", "Agent")]

    area = models.ForeignKey(
        Area, null=True, blank=True, on_delete=models.SET_NULL, related_name="slices",
    )
    # Denormalized from area.org so the per-org number uniqueness constraint is
    # expressible at all — UniqueConstraint cannot traverse relations, and the
    # readers that need the guarantee (get_slice_by_ref, resolve_ref) scope by
    # org, not area. Safe because set_slice_area() refuses cross-org moves,
    # making a slice's org immutable after creation: a cached projection of a
    # fixed fact, not a second mutable copy.
    org = models.ForeignKey("core.Org", on_delete=models.CASCADE, related_name="slices")
    title = models.CharField(max_length=300)
    spec = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    tags = models.ManyToManyField(Tag, blank=True, related_name="slices")
    rank = models.CharField(max_length=255)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="human")
    number = models.PositiveIntegerField(null=True, blank=True)
    external_key = models.CharField(max_length=200, blank=True, default="")
    assignee = models.ForeignKey(
        "core.OrgMember", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_slices",
    )
    constraints = models.TextField(blank=True, default="")
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["rank"]
        constraints = [
            # Mirrors uniq_ticket_number_per_org (0034). allocate_number()
            # already serializes minting, but admin/import/raw-ORM paths bypass
            # it — and get_slice_by_ref() resolves with .get(), so a collision
            # raises MultipleObjectsReturned, which that caller does not catch.
            # resolve_ref() uses .first() and would silently pick either row.
            models.UniqueConstraint(
                fields=["org", "number"],
                condition=models.Q(number__isnull=False),
                name="uniq_slice_number_per_org",
            ),
            # Mirrors uniq_ticket_external_key_per_org (0034): safe against
            # concurrent agent retries keyed by an external system's id.
            models.UniqueConstraint(
                fields=["org", "external_key"],
                condition=~models.Q(external_key=""),
                name="uniq_slice_external_key_per_org",
            ),
        ]

    def __str__(self):
        return self.title


# Module-level so `Meta` can see it: a nested class body does not resolve names
# from the enclosing class namespace.
TICKET_RESOLVED_STATUSES = ("promoted", "dismissed", "duplicate")


class Ticket(models.Model):
    """A pre-commit capture: the triage tier upstream of a Slice.

    A Ticket answers exactly one question — "are we doing this?" — and its
    status stops moving the moment that question is answered. It never tracks
    delivery: once promoted, the Slice is the single source of truth for
    progress (read it via `ticket.slice.status`). Keeping a second copy of
    "is it done yet" here is what drifts, so we don't."""

    STATUS_CHOICES = [
        ("open", "Open"),            # not yet triaged — this is the Inbox
        ("promoted", "Promoted"),    # became a Slice; progress lives there
        ("dismissed", "Dismissed"),  # decided against, before any work started
        ("duplicate", "Duplicate"),  # already covered elsewhere
    ]
    RESOLVED_STATUSES = TICKET_RESOLVED_STATUSES
    SOURCE_CHOICES = [("human", "Human"), ("agent", "Agent")]

    org = models.ForeignKey("core.Org", on_delete=models.CASCADE, related_name="tickets")
    area = models.ForeignKey(Area, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    number = models.PositiveIntegerField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="human")
    created_by = models.ForeignKey(
        "core.OrgMember", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_tickets",
    )
    external_key = models.CharField(max_length=200, blank=True, default="")
    # Many Tickets may point at one Slice: promotion links the origin (whose
    # number the Slice inherits), absorb links the rest. The accessor spelling
    # `ticket.slice` is unchanged from the OneToOne's related_name that this
    # replaces, so every read-side caller keeps working untouched.
    slice = models.ForeignKey(
        "core.Slice", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tickets",
    )
    rank = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["rank"]
        constraints = [
            # Numbers are minted per-org by allocate_number() under a row lock,
            # but admin/import/raw-ORM paths bypass that — enforce it in the DB.
            # Ticket and Slice share one number space; uniqueness is per-table
            # (a promoted Ticket's Slice deliberately reuses its number).
            models.UniqueConstraint(
                fields=["org", "number"],
                condition=models.Q(number__isnull=False),
                name="uniq_ticket_number_per_org",
            ),
            # Makes create_ticket(external_key=...) safe against concurrent
            # agent retries, not just sequential ones.
            models.UniqueConstraint(
                fields=["org", "external_key"],
                condition=~models.Q(external_key=""),
                name="uniq_ticket_external_key_per_org",
            ),
            # Doubles as a status whitelist: anything outside these four values
            # satisfies neither branch.
            models.CheckConstraint(
                condition=(
                    models.Q(status="open", resolved_at__isnull=True)
                    | models.Q(status__in=TICKET_RESOLVED_STATUSES, resolved_at__isnull=False)
                ),
                name="ticket_resolved_at_matches_status",
            ),
        ]
        indexes = [
            models.Index(fields=["org", "status", "rank"], name="ticket_inbox_order_idx"),
            models.Index(fields=["org", "status", "created_at"], name="ticket_stale_idx"),
        ]

    def __str__(self):
        return self.title


class Bite(models.Model):
    STATUS_CHOICES = [
        ("todo", "Todo"),
        ("doing", "Doing"),
        ("done", "Done"),
        ("dropped", "Dropped"),
    ]
    SOURCE_CHOICES = [("human", "Human"), ("agent", "Agent")]

    plan = models.ForeignKey("Plan", on_delete=models.CASCADE, related_name="bites")
    slice = models.ForeignKey(
        "Slice", null=True, blank=True, on_delete=models.CASCADE, related_name="bites",
    )
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="todo")
    rank = models.CharField(max_length=255)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="human")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["rank"]

    def __str__(self):
        return self.title


class Plan(models.Model):
    SOURCE_CHOICES = [("human", "Human"), ("agent", "Agent")]

    slice = models.ForeignKey(Slice, on_delete=models.CASCADE, related_name="plans")
    title = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField(blank=True, default="")
    constraints = models.TextField(blank=True, default="")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="human")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
