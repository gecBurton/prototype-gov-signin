from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from users.models import AllowedEmailDomain, Membership, SignInEvent, Team, User


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


class AllowedEmailDomainInline(admin.TabularInline):
    model = AllowedEmailDomain
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name",)
    inlines = (MembershipInline, AllowedEmailDomainInline)


@admin.register(SignInEvent)
class SignInEventAdmin(admin.ModelAdmin):
    """Read-only audit view of application sign-ins.

    application_client_id/application_name/team are a denormalised snapshot
    (see users.models.SignInEvent) rather than a foreign key, since
    applications themselves live in Hydra, not this database.
    """

    list_display = ("created", "user", "application_name", "team")
    list_filter = ("team", "created")
    search_fields = ("user__email", "application_name")
    date_hierarchy = "created"
    readonly_fields = (
        "user",
        "application_client_id",
        "application_name",
        "team",
        "created",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = (MembershipInline,)
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )
