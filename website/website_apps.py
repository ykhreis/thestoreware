from django.apps import AppConfig
from django.utils.module_loading import import_module


class WebsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "website"

    def import_models(self):
        self.models = self.apps.all_models[self.label]
        self.models_module = import_module("website.website_models")