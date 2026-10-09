from django.urls import path

from . import analytics_views

app_name = 'analytics'

urlpatterns = [
    path('', analytics_views.dashboard, name='dashboard'),
]
