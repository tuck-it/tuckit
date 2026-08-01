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


# No PlanInline. There is no Plan model at all now — 0050 dropped the table
# along with Bite.plan, whose on_delete=CASCADE was what made a staff-facing
# inline dangerous: deleting a plan row took a slice's steps with it.


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
