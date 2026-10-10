from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),

    # Django built-in language switch endpoint.
    # Provides the named URL "set_language" used by EN | العربية | FR.
    path("i18n/", include("django.conf.urls.i18n")),

    path("ai-agent/", include("mentor.ai_agent_urls")),
    path("", include("website.website_urls")),
    path("analytics/", include("analytics.analytics_urls")),
]
