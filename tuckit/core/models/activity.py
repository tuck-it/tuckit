from django.db import models


class ActivityEvent(models.Model):
    # Same name and same values as Slice.source / Bite.source / Area.source:
    # one axis, one word. It used to be called `actor`, which read as "who did
    # this" and is not what it answers — a misreading that reached a written
    # spec before anyone opened the code.
    SOURCE_CHOICES = [("human", "Human"), ("agent", "Agent")]
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
    # No "ticket". 0045 retargeted every ticket event whose ticket it could
    # still find; 0050 deleted the leftovers — the ones pointing at tickets
    # already gone, which no reader could resolve to anything. Keeping the
    # choice would leave a value nothing can write and nothing can render.
    TARGET_CHOICES = [("slice", "Slice"), ("bite", "Bite"), ("area", "Area")]

    org = models.ForeignKey("core.Org", on_delete=models.CASCADE, related_name="activity")
    # HOW the write arrived — human|agent — not who was driving. An agent
    # acting for someone records source="agent" AND that person in `member`
    # below. All four combinations occur: a machine token is agent with no
    # member, and rows written before member existed are human with none.
    # Status dots, the onboarding "connected" check and the Home new-count all
    # read this one.
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    # WHO was acting. Null for legacy ApiToken callers, which carry no user at
    # all, so those rows are simply unattributed — a guess would be worse.
    # SET_NULL only fires when the account itself is deleted: leaving an org no
    # longer destroys the membership row (see migration 0050), which is what
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
        return f"{self.source} {self.verb} {self.target_type}:{self.target_id}"
