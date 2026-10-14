from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.shortcuts import render
from datetime import timedelta

# Unique Analytics model module name
from .analytics_models import Visitor, VisitSession, PageView
from website.website_models import WebsiteSubscriber


@staff_member_required(login_url="/admin/login/")
def dashboard(request):
    """
    Private TheStoreWare analytics dashboard.
    Shows anonymous visitor/session/page-view activity.
    """

    total_visitors = Visitor.objects.count()
    total_sessions = VisitSession.objects.count()
    unique_ips = (
        VisitSession.objects
        .exclude(ip_address__isnull=True)
        .exclude(ip_address="")
        .values("ip_address")
        .distinct()
        .count()
    )
    total_page_views = PageView.objects.count()
    todays_visitors = Visitor.objects.filter(first_seen__date=timezone.localdate()).count()
    total_subscribers = WebsiteSubscriber.objects.filter(is_active=True).count()

    # 30-day trend: new unique visitors and sessions per calendar day.
    trend_start_date = timezone.localdate() - timedelta(days=29)

    visitor_rows = (
        Visitor.objects
        .filter(first_seen__date__gte=trend_start_date)
        .annotate(day=TruncDate("first_seen"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    session_rows = (
        VisitSession.objects
        .filter(started_at__date__gte=trend_start_date)
        .annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )

    visitor_by_day = {row["day"]: row["total"] for row in visitor_rows}
    session_by_day = {row["day"]: row["total"] for row in session_rows}

    visitor_trend = []
    for offset in range(30):
        day = trend_start_date + timedelta(days=offset)
        visitor_trend.append({
            "date": day.strftime("%d %b"),
            "visitors": visitor_by_day.get(day, 0),
            "sessions": session_by_day.get(day, 0),
        })

    recent_subscribers = (
        WebsiteSubscriber.objects
        .select_related("visitor", "visit_session")
        .order_by("-subscribed_at")[:25]
    )

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

    devices = list(
        VisitSession.objects
        .values("device_type")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    for item in devices:
        item["percentage"] = round((item["total"] / total_sessions * 100), 1) if total_sessions else 0

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

    # Country breakdown must reconcile exactly with Total Visitors.
    # Count each Visitor once, using the country from that visitor's latest session.
    # Visitors without a resolved country are grouped as Unknown / Not Identified.
    country_totals = {}

    visitors_with_latest_session = (
        Visitor.objects
        .prefetch_related("sessions")
        .all()
    )

    for visitor in visitors_with_latest_session:
        latest_session = max(
            visitor.sessions.all(),
            key=lambda session: session.started_at,
            default=None,
        )

        country_name = ""
        if latest_session is not None:
            country_name = (latest_session.country_name or "").strip()

        country_name = country_name or "Unknown / Not Identified"
        country_totals[country_name] = country_totals.get(country_name, 0) + 1

    countries = [
        {
            "country_name": country_name,
            "total": total,
            "percentage": round((total / total_visitors * 100), 1) if total_visitors else 0,
        }
        for country_name, total in sorted(
            country_totals.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    context = {
        "total_visitors": total_visitors,
        "total_sessions": total_sessions,
        "unique_ips": unique_ips,
        "total_page_views": total_page_views,
        "todays_visitors": todays_visitors,
        "total_subscribers": total_subscribers,
        "visitor_trend": visitor_trend,
        "recent_subscribers": recent_subscribers,
        "recent_sessions": recent_sessions,
        "popular_pages": popular_pages,
        "devices": devices,
        "browsers": browsers,
        "operating_systems": operating_systems,
        "countries": countries,
    }

    return render(request, "analytics/dashboard.html", context)
