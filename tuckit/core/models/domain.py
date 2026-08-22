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
    # 1 is the most urgent, matching the P1 convention every tracker uses.
    # Integers rather than names on purpose: the NUMBERS are the vocabulary and
    # Org.priority_policy supplies their meaning, so the product shipping
    # "Urgent"/"High" would put a second vocabulary on the same screen and give
    # a classifying agent two things to obey. Integer rather than CharField
    # because string ordering follows the database collation, which has already
    # bitten `rank` here once.
    PRIORITY_CHOICES = [(n, str(n)) for n in range(1, 6)]

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
    # NULL means nobody has ranked this yet -- a real state, not a missing
    # value, and the one every existing row starts in. Every ORDER BY that
    # touches this column must say nulls_last explicitly: Postgres puts NULLs
    # last in ASC and sqlite puts them first, so the default sorts the board
    # one way locally and the other way in production.
    priority = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=PRIORITY_CHOICES,
    )
    # How this slice was decided: {"nodes": [...]} -- the questions that were
    # asked, every option that was weighed, and which one won. Append-only.
    #
    # It answers a DIFFERENT question from `spec`. `spec` is where we arrived;
    # this is how we got there. They do not compete, so neither replaces nor
    # clears the other -- an earlier version cleared this on a spec write and
    # destroyed the record permanently (TP-238).
    decision_tree = models.JSONField(default=dict, blank=True)
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates",
    )
    created_by = models.ForeignKey(
        "core.OrgMember", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_slices",
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


class Bite(models.Model):
    STATUS_CHOICES = [
        ("todo", "Todo"),
        ("doing", "Doing"),
        ("done", "Done"),
        ("dropped", "Dropped"),
    ]
    SOURCE_CHOICES = [("human", "Human"), ("agent", "Agent")]

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
