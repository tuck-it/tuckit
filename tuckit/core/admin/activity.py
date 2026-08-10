from django.contrib import admin

from tuckit.core.models import ActivityEvent


@admin.register(ActivityEvent)
class ActivityEventAdmin(admin.ModelAdmin):
    """Append-only activity log — read-only in the admin."""

    list_display = ("created_at", "source", "verb", "target_type", "target_label")
    list_filter = ("verb", "source", "target_type")
    search_fields = ("target_label",)
    readonly_fields = (
        "org",
        "source",
        "verb",
        "target_type",
        "target_id",
        "target_label",
        "from_value",
        "to_value",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return True
