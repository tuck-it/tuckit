from django.db import models


class ActivityEvent(models.Model):
    ACTOR_CHOICES = [("human", "Human"), ("agent", "Agent")]
    VERB_CHOICES = [
        ("created", "created"),
        ("status_changed", "status changed"),
        ("moved", "moved"),
        ("shipped", "shipped"),
        ("dropped", "dropped"),
        ("planned", "planned"),
        ("noted", "noted"),
        ("promoted", "promoted"),
        ("dismissed", "dismissed"),
        ("deleted", "deleted"),
        # LEGACY — never written by current code, kept so historical rows keep
        # rendering. 'triaged' predates the Ticket model; 'closed' predates the
        # promoted/dismissed split (it conflated "shipped" with "won't do").
        ("triaged", "triaged"),
        ("closed", "closed"),
    ]
    TARGET_CHOICES = [("slice", "Slice"), ("bite", "Bite"), ("area", "Area"), ("ticket", "Ticket")]

    org = models.ForeignKey("core.Org", on_delete=models.CASCADE, related_name="activity")
    # WHICH CHANNEL the write arrived on — human|agent — not who was driving.
    # An agent acting for someone records actor="agent" AND that person in
    # `member` below; the two are separate axes and reading either as the other
    # is the confusion this field's name invites. Status dots, the onboarding
    # "connected" check and the Home new-count all read this one.
    actor = models.CharField(max_length=10, choices=ACTOR_CHOICES)
    # WHO was acting. Null for legacy ApiToken callers, which carry no user at
    # all, so those rows are simply unattributed — a guess would be worse.
    # SET_NULL only fires when the account itself is deleted: leaving an org no
    # longer destroys the membership row (see migration 0047), which is what
    # makes it safe for an immutable log to point here.
    member = models.ForeignKey(
        "core.OrgMember", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="activity",
    )
    verb = models.CharField(max_length=20, choices=VERB_CHOICES)
    target_type = models.CharField(max_length=10, choices=TARGET_CHOICES)
    target_id = models.IntegerField()
    target_label = models.CharField(max_length=300)
    from_value = models.CharField(max_length=50, blank=True, default="")
    to_value = models.CharField(max_length=50, blank=True, default="")
    body = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["org", "-created_at"]),
            models.Index(fields=["org", "id"]),
        ]

    def __str__(self):
        return f"{self.actor} {self.verb} {self.target_type}:{self.target_id}"
