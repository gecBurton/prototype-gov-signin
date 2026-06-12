from django.contrib.admin.apps import AdminConfig


class IAMAdminConfig(AdminConfig):
    """Replaces django.contrib.admin so the default admin site is the
    allauth-authenticated ``IAMAdminSite``; existing ``@admin.register``
    registrations then need no changes.

    Kept out of ``users.apps`` so it is not mistaken for the ``users`` app's own
    AppConfig (Django would see two and refuse to pick a default).
    """

    default_site = "users.admin_site.IAMAdminSite"
