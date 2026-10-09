from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.utils import timezone
from django.shortcuts import render

# Unique Analytics model module name
from .analytics_models import Visitor, VisitSession, PageView


@login_required(login_url="/admin/login/")
def dashboard(request):
    """
    Private TheStoreWare analytics dashboard.
    Shows anonymous visitor/session/page-view activity.
    """

    total_visitors = Visitor.objects.count()
    total_sessions = VisitSession.objects.count()
    total_page_views = PageView.objects.count()
    todays_visitors = Visitor.objects.filter(first_seen__date=timezone.localdate()).count()

    recent_sessions = (
        VisitSession.objects
        .select_related("visitor")
        .order_by("-started_at")[:25]
    )

    popular_pages = (
        PageView.objects
        .values("path")
        .annotate(views=Count("id"))
        .order_by("-views")[:10]
    )

    devices = (
        VisitSession.objects
        .values("device_type")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    browsers = (
        VisitSession.objects
        .values("browser")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    operating_systems = (
        VisitSession.objects
        .values("operating_system")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    countries = (
        VisitSession.objects
        .exclude(country_name="")
        .values("country_name")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )

    context = {
        "total_visitors": total_visitors,
        "total_sessions": total_sessions,
        "total_page_views": total_page_views,
        "todays_visitors": todays_visitors,
        "recent_sessions": recent_sessions,
        "popular_pages": popular_pages,
        "devices": devices,
        "browsers": browsers,
        "operating_systems": operating_systems,
        "countries": countries,
    }

    return render(request, "analytics/dashboard.html", context)
