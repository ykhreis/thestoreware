from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("ai-agent/", include("mentor.ai_agent_urls")),
    path("", include("website.website_urls")),
    path("analytics/", include("analytics.analytics_urls")),
]
