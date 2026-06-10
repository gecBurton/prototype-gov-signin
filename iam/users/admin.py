from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from oauth2_provider.admin import ApplicationAdmin
from oauth2_provider.models import get_application_model

from users.models import AllowedEmailDomain, Membership, Team, User

Application = get_application_model()

admin.site.unregister(Application)


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


class CustomApplicationAdmin(ApplicationAdmin):
    pass


admin.site.register(Application, CustomApplicationAdmin)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = (MembershipInline,)
