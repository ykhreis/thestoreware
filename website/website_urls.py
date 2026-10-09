from django.urls import path
from . import website_views

urlpatterns = [
    path("", website_views.home, name="home"),
    path("area/<slug:slug>/", website_views.area_detail, name="area_detail"),
    path("feedback/", website_views.submit_feedback, name="submit_feedback"),
]