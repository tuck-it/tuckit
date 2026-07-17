from django.contrib import admin

from tuckit.core.models import ApiToken, Workspace, WorkspaceStatSnapshot


class ApiTokenInline(admin.TabularInline):
    model = ApiToken
    extra = 0
    fields = ("name", "token_hash", "last_used_at", "created_at")
    readonly_fields = ("token_hash", "last_used_at", "created_at")


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "org", "created_at")
    list_filter = ("org",)
    search_fields = ("name", "slug")
    autocomplete_fields = ("org",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [ApiTokenInline]


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "last_used_at", "created_at")
    search_fields = ("name", "workspace__name")
    autocomplete_fields = ("workspace",)
    # token_hash is a secret; keep it read-only.
    readonly_fields = ("token_hash", "last_used_at", "created_at")


@admin.register(WorkspaceStatSnapshot)
class WorkspaceStatSnapshotAdmin(admin.ModelAdmin):
    """Derived, snapshot data — read-only."""

    list_display = (
        "workspace",
        "date",
        "building_ct",
        "backlog_ct",
        "shipped_week_ct",
        "attention_ct",
    )
    list_filter = ("date",)
    search_fields = ("workspace__name",)
    readonly_fields = (
        "workspace",
        "date",
        "building_ct",
        "backlog_ct",
        "shipped_week_ct",
        "attention_ct",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return True
