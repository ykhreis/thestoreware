from django.apps import AppConfig
from django.utils.module_loading import import_module


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "analytics"

    def import_models(self):
        self.models = self.apps.all_models[self.label]
        self.models_module = import_module("analytics.analytics_models")