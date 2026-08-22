from django.db import models


class CanvasWatch(models.Model):
    """A short-lived capability channel between a browser click and an agent.

    The design conversation runs in a terminal that holds tuckit credentials;
    the poll loop waiting for the human's click does not, and must not -- the
    reason this row exists at all is to avoid teaching a shell script how to
    authenticate. So it answers exactly one question, "has a choice landed
    yet", and carries no slice content: the answer is a node id the agent
    itself authored.

    Only the token's SHA-256 hash is stored, exactly as for an OAuth access
    token -- whoever holds the URL holds the capability.
    """
    org = models.ForeignKey(
        "core.Org", on_delete=models.CASCADE, related_name="canvas_watches")
    slice = models.ForeignKey(
        "core.Slice", on_delete=models.CASCADE, related_name="canvas_watches")
    token_hash = models.CharField(max_length=64, unique=True)
    # The question this watch was opened for. A slice can have several open at
    # once (the skill calls propose per question), and an answer to one is not
    # an answer to another -- without this, the first click empties every
    # watch's `choice` and the second click reaches nobody.
    question_id = models.CharField(max_length=200, blank=True, default="")
    # The node id that was picked; empty until someone picks one.
    choice = models.CharField(max_length=200, blank=True, default="")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"watch on slice:{self.slice_id}"
