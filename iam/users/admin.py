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
