from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from oauth2_provider.admin import ApplicationAdmin
from oauth2_provider.models import get_application_model

from users.models import Team, User

Application = get_application_model()

admin.site.unregister(Application)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name",)


class CustomApplicationAdmin(ApplicationAdmin):
    pass


admin.site.register(Application, CustomApplicationAdmin)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Team", {"fields": ("team",)}),)
