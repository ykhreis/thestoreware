from django.urls import path
from . import website_views

urlpatterns = [
    path("", website_views.home, name="home"),
    path("area/<slug:slug>/", website_views.area_detail, name="area_detail"),
    path("feedback/", website_views.submit_feedback, name="submit_feedback"),
    path("subscribe/", website_views.subscribe, name="subscribe"),
    path("subscribe/profile/", website_views.subscribe_profile, name="subscribe_profile"),
]