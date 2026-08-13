from django.db import models

from tuckit.core.models.org import Org


class ThrottleEpisode(models.Model):
    """One row per EPISODE of an agent connection being rate limited -- never
    one row per refused request.

    The limiter refuses from process memory; this table exists only so an
    operator can see which connection is hitting the ceiling. A row is written
    when a bucket goes from passing to blocking and then suppressed for five
    minutes, so a connection hammering ten times a second still produces at
    most twelve rows an hour. Counting rows tells you how often something went
    wrong, and never how many requests were refused.

    There is no `scope` column on purpose: only connection refusals are
    recorded. An org-wide refusal is an incident and goes to the log instead,
    where `label` would have had nothing to name.
    """

    org = models.ForeignKey(
        Org, on_delete=models.CASCADE, related_name="throttle_episodes"
    )
    label = models.CharField(max_length=300)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["org", "-at"])]

    def __str__(self):
        return f"{self.label} @ {self.at:%Y-%m-%d %H:%M}"
