from django.db import models


class SlackInstall(models.Model):
    """One Slack workspace bound to one org.

    OneToOne in both directions on purpose: connecting a second workspace to
    the same org, or the same workspace to two orgs, is a question about who
    can write where, and it is not one this slice answers.
    """
    org = models.OneToOneField("core.Org", on_delete=models.CASCADE, related_name="slack_install")
    team_id = models.CharField(max_length=32, unique=True)
    team_name = models.CharField(max_length=200, blank=True, default="")
    bot_token = models.CharField(max_length=255)
    bot_user_id = models.CharField(max_length=32)
    installed_by = models.ForeignKey(
        "core.OrgMember", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.team_name or self.team_id} -> {self.org.slug}"


class SlackIdentity(models.Model):
    """Which person a Slack user is, for this install.

    Points at OrgMember rather than User so a write can be attributed to the
    membership that made it. Note that this FK is NOT the access gate: a
    membership ends by stamping ended_at, not by deletion, and Meta's
    base_manager_name = "all_objects" makes forward FK access resolve ended
    memberships deliberately. Whether a departed member may still write is
    decided by the ended_at filter in identity.resolve_member().
    """
    install = models.ForeignKey(SlackInstall, on_delete=models.CASCADE, related_name="identities")
    slack_user_id = models.CharField(max_length=32)
    member = models.ForeignKey("core.OrgMember", on_delete=models.CASCADE, related_name="slack_identities")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["install", "slack_user_id"], name="uniq_slack_identity_per_install",
            ),
        ]


class SlackEvent(models.Model):
    """The idempotency ledger.

    Slack retries an event it did not get a 200 for within three seconds, and
    a cold start eats that budget, so retries are a normal path here rather
    than a rare fault. The unique constraint is the real defence: a race
    between the original and its retry is resolved by the database, not by a
    read-then-write in application code.
    """
    event_id = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class SlackUnfurl(models.Model):
    """When a ref was last expanded, per channel.

    A ref repeated in an active channel should not redraw a card every time;
    Linear uses a 60-minute window and it reads well.

    `channel` is part of the key because the window belongs to a conversation,
    not to the workspace. Without it, one person sharing a ref in #eng silences
    it everywhere else for an hour: the next person pastes the same link in
    another channel and gets nothing, with no way to find out why -- unfurling
    is the one path forbidden to explain its own failures, in logs included.
    """
    install = models.ForeignKey(SlackInstall, on_delete=models.CASCADE, related_name="unfurls")
    channel = models.CharField(max_length=32)
    ref = models.CharField(max_length=32)
    last_unfurled_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["install", "channel", "ref"], name="uniq_slack_unfurl_per_channel_ref",
            ),
        ]
