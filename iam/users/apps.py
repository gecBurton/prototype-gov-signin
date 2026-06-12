from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = "users"

    def ready(self):
        # Register the login signal that syncs admin status from ADMIN_USERS.
        from . import signals  # noqa: F401
