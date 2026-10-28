from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.research"
    label = "research"

    def ready(self):
        from . import receivers  # noqa: F401  (registers the control-group reminder filter)
