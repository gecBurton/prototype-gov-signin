from django.contrib import admin
from oauth2_provider.admin import ApplicationAdmin
from oauth2_provider.models import get_application_model

Application = get_application_model()

admin.site.unregister(Application)


class CustomApplicationAdmin(ApplicationAdmin):
    filter_horizontal = ("owners",)


admin.site.register(Application, CustomApplicationAdmin)
