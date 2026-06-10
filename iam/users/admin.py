from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from users.models import AllowedEmailDomain, Membership, Team, User


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
