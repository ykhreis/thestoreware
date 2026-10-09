from django.apps import AppConfig


class MentorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mentor"
    verbose_name = "AI-Agent"

    def ready(self):
        # Load AI-Agent models from the uniquely named model module.
        from . import ai_agent_models  # noqa: F401