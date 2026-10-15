from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.db.models.functions import TruncDate, Coalesce
from django.utils import timezone
from django.shortcuts import render
from datetime import timedelta, datetime

# Unique Analytics model module name
from .analytics_models import Visitor, VisitSession, PageView
from website.website_models import WebsiteSubscriber


def _parse_date(value):
    """Parse YYYY-MM-DD safely; return None when missing/invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@staff_member_required(login_url="/admin/login/")
def dashboard(request):
    """
    Private TheStoreWare analytics dashboard.
    Shows anonymous visitor/session/page-view activity.

    Optional GET filters:
      ?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
    With no dates supplied, the dashboard keeps the overall summary while
    Recent Sessions defaults to Today.
    """

    today = timezone.localdate()
    from_date = _parse_date(request.GET.get("from_date"))
    to_date = _parse_date(request.GET.get("to_date"))

    # If only one side is supplied, use it for both sides.
    if from_date and not to_date:
        to_date = from_date
    elif to_date and not from_date:
        from_date = to_date

    # Protect against reversed ranges.
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    has_date_filter = bool(from_date and to_date)

    # Overall totals remain available in the headline cards.
    total_visitors = Visitor.objects.count()
    total_sessions = VisitSession.objects.count()
    # Count unique stored IP values. Strip whitespace first so blank/space-only
    # values are not treated as real IPs.
    all_ip_values = {
        (value or "").strip()
        for value in VisitSession.objects.values_list("ip_address", flat=True)
        if (value or "").strip()
    }
    unique_ips = len(all_ip_values)
    total_page_views = PageView.objects.count()
    todays_visitors = Visitor.objects.filter(first_seen__date=today).count()
    total_subscribers = WebsiteSubscriber.objects.filter(is_active=True).count()

    # Session date range: explicit selection, otherwise Today.
    session_from_date = from_date if has_date_filter else today
    session_to_date = to_date if has_date_filter else today

    filtered_sessions_qs = VisitSession.objects.filter(
        started_at__date__gte=session_from_date,
        started_at__date__lte=session_to_date,
    )

    filtered_session_count = filtered_sessions_qs.count()
    filtered_ip_values = {
        (value or "").strip()
        for value in filtered_sessions_qs.values_list("ip_address", flat=True)
        if (value or "").strip()
    }

    # If sessions exist but none contains an IP value, show N/A rather than
    # a misleading zero. Otherwise count distinct IP values in the period.
    filtered_unique_ips = (
        len(filtered_ip_values)
        if filtered_ip_values
        else ("N/A" if filtered_session_count > 0 else 0)
    )

    # Count actual visitors who had at least one session in the selected period.
    filtered_visitors = (
        filtered_sessions_qs
        .exclude(visitor__isnull=True)
        .values("visitor_id")
        .distinct()
        .count()
    )

    # Page views for sessions in the selected period.
    filtered_page_views = PageView.objects.filter(
        session__started_at__date__gte=session_from_date,
        session__started_at__date__lte=session_to_date,
    ).count()

    # Visitors whose first visit occurred in the selected period.
    filtered_new_visitors = Visitor.objects.filter(
        first_seen__date__gte=session_from_date,
        first_seen__date__lte=session_to_date,
    ).count()

    # 30-day trend: new unique visitors and sessions per calendar day.
    trend_start_date = today - timedelta(days=29)

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

    # Show up to 250 sessions for the chosen date/range instead of only the
    # latest 25 sessions across the whole database.
    recent_sessions = (
        filtered_sessions_qs
        .select_related("visitor")
        .order_by("-started_at")[:250]
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

        # Date-filter context.
        "filter_from_date": session_from_date.strftime("%Y-%m-%d"),
        "filter_to_date": session_to_date.strftime("%Y-%m-%d"),
        "has_date_filter": has_date_filter,
        "filtered_session_count": filtered_session_count,
        "filtered_visitors": filtered_visitors,
        "filtered_unique_ips": filtered_unique_ips,
        "filtered_page_views": filtered_page_views,
        "filtered_new_visitors": filtered_new_visitors,
        "today_iso": today.strftime("%Y-%m-%d"),
        "yesterday_iso": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
        "last7_iso": (today - timedelta(days=6)).strftime("%Y-%m-%d"),
        "last30_iso": (today - timedelta(days=29)).strftime("%Y-%m-%d"),
    }

    return render(request, "analytics/dashboard.html", context)
