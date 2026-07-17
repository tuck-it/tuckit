from django.db import models

from tuckit.core.models.workspace import Workspace


class ActivityEvent(models.Model):
    ACTOR_CHOICES = [("human", "Human"), ("agent", "Agent")]
    VERB_CHOICES = [
        ("created", "created"),
        ("status_changed", "status changed"),
        ("triaged", "triaged"),
        ("moved", "moved"),
        ("shipped", "shipped"),
        ("dropped", "dropped"),
        ("planned", "planned"),
    ]
    TARGET_CHOICES = [("slice", "Slice"), ("bite", "Bite"), ("area", "Area")]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="activity", null=True, blank=True)
    org = models.ForeignKey("core.Org", on_delete=models.CASCADE, related_name="activity")
    actor = models.CharField(max_length=10, choices=ACTOR_CHOICES)
    verb = models.CharField(max_length=20, choices=VERB_CHOICES)
    target_type = models.CharField(max_length=10, choices=TARGET_CHOICES)
    target_id = models.IntegerField()
    target_label = models.CharField(max_length=300)
    from_value = models.CharField(max_length=50, blank=True, default="")
    to_value = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"]),
            models.Index(fields=["org", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.actor} {self.verb} {self.target_type}:{self.target_id}"
