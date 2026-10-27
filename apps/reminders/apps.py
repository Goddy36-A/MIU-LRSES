from django.apps import AppConfig


class RemindersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reminders"
    label = "reminders"

    def ready(self):
        from . import receivers  # noqa: F401  (connects the lecture_changed handler)
