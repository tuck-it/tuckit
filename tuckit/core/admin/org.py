from django.contrib import admin

from tuckit.core.models import Invitation, Org, OrgMember


class OrgMemberInline(admin.TabularInline):
    model = OrgMember
    extra = 0
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)

    def get_queryset(self, request):
        # Support has to be able to see ended memberships — they are the reason
        # old work still has a name on it. The default manager hides them.
        return OrgMember.all_objects.all()


@admin.register(Org)
class OrgAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    search_fields = ("name", "slug")
    readonly_fields = ("created_at",)
    inlines = [OrgMemberInline]


@admin.register(OrgMember)
class OrgMemberAdmin(admin.ModelAdmin):
    list_display = ("user", "org", "role", "created_at", "ended_at")
    list_filter = ("role", "ended_at")
    search_fields = ("user__email", "org__name")
    autocomplete_fields = ("user", "org")
    readonly_fields = ("created_at",)

    def get_queryset(self, request):
        # all_objects, not the fail-closed default: an ended membership that is
        # invisible in the admin is one support cannot explain or restore.
        return OrgMember.all_objects.all()


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "org", "role", "accepted_at", "created_at")
    list_filter = ("role", "accepted_at")
    search_fields = ("email", "org__name")
    autocomplete_fields = ("org",)
    readonly_fields = ("created_at",)
