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
    is_triage = models.BooleanField(default=False)
    rank = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("org", "slug")]
        ordering = ["rank"]

    def __str__(self):
        return self.name


class Slice(models.Model):
    STATUS_CHOICES = [
        ("idea", "Idea"),
        ("planned", "Planned"),
        ("building", "Building"),
        ("shipped", "Shipped"),
        ("dropped", "Dropped"),
    ]
    SOURCE_CHOICES = [("human", "Human"), ("agent", "Agent")]

    area = models.ForeignKey(Area, on_delete=models.CASCADE, related_name="slices")
    title = models.CharField(max_length=300)
    spec = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="idea")
    tags = models.ManyToManyField(Tag, blank=True, related_name="slices")
    rank = models.CharField(max_length=255)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="human")
    number = models.PositiveIntegerField(null=True, blank=True)
    assignee = models.ForeignKey(
        "core.OrgMember", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_slices",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["rank"]

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
