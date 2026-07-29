from django.contrib import admin

from tuckit.core.models import Area, Bite, Slice, Tag


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "org")
    list_filter = ("org",)
    search_fields = ("name",)


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "org", "archived")
    list_filter = ("org", "archived")
    search_fields = ("name", "slug")
    readonly_fields = ("created_at", "updated_at")


# No PlanInline. Nothing in the product creates a Plan any more, but
# Bite.plan is still on_delete=CASCADE this release (0045 leaves it populated
# for every pre-release bite; the column drop is 0047), so an inline with
# delete checkboxes on SliceAdmin was a live, staff-reachable button that
# destroyed a slice's steps with no undo — in a release whose whole claim is
# that nothing is irreversible.


@admin.register(Slice)
class SliceAdmin(admin.ModelAdmin):
    list_display = ("title", "area", "status", "source", "created_at")
    list_filter = ("status", "source")
    search_fields = ("title",)
    autocomplete_fields = ("area",)
    filter_horizontal = ("tags",)
    readonly_fields = ("created_at", "updated_at", "completed_at")


@admin.register(Bite)
class BiteAdmin(admin.ModelAdmin):
    list_display = ("title", "slice", "status", "source")
    list_filter = ("status", "source")
    search_fields = ("title",)
    readonly_fields = ("created_at", "updated_at")
