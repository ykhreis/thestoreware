from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Min, Max
from django.db.models.functions import TruncDate, Coalesce
from django.utils import timezone
from django.shortcuts import render
from datetime import timedelta, datetime

# Unique Analytics model module name
from .analytics_models import Visitor, VisitSession, PageView, SecurityRequest
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
    raw_total_visitors = Visitor.objects.count()
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

    # ---------------------------------------------------------
    # REALISTIC VISITOR ESTIMATE / AUTOMATED TRAFFIC
    # ---------------------------------------------------------
    # A cookie-less bot/scanner can create a new Visitor row on every request.
    # Do not delete those records: classify highly repetitive IP activity for
    # reporting while keeping the raw traffic available for security analysis.
    #
    # Conservative rule for v1:
    #   - at least 10 distinct visitor identities from the same IP in the period,
    #   - at least 80% of that IP's sessions are single-page sessions, and
    #   - average page views per session is <= 1.5.
    #
    # This avoids treating a normal shared office IP as automated merely because
    # several legitimate users browse from the same public address.
    suspicious_ips = set()
    suspicious_visitor_ids = set()

    ip_activity = (
        filtered_sessions_qs
        .exclude(ip_address__isnull=True)
        .exclude(ip_address='')
        .values('ip_address')
        .annotate(
            session_count=Count('id'),
            visitor_count=Count('visitor_id', distinct=True),
        )
    )

    for row in ip_activity:
        ip_address = row['ip_address']
        visitor_count = row['visitor_count'] or 0
        session_count = row['session_count'] or 0

        if visitor_count < 10 or session_count < 10:
            continue

        ip_sessions = filtered_sessions_qs.filter(ip_address=ip_address)
        single_page_sessions = ip_sessions.filter(page_view_count__lte=1).count()
        total_page_views_for_ip = sum(
            ip_sessions.values_list('page_view_count', flat=True)
        )

        single_page_ratio = (
            single_page_sessions / session_count if session_count else 0
        )
        avg_pages_per_session = (
            total_page_views_for_ip / session_count if session_count else 0
        )

        if single_page_ratio >= 0.80 and avg_pages_per_session <= 1.5:
            suspicious_ips.add(str(ip_address))
            suspicious_visitor_ids.update(
                ip_sessions.exclude(visitor__isnull=True)
                .values_list('visitor_id', flat=True)
                .distinct()
            )

    suspicious_visitor_count = len(suspicious_visitor_ids)
    suspicious_ip_count = len(suspicious_ips)
    estimated_human_visitors = max(
        filtered_visitors - suspicious_visitor_count,
        0,
    )

    # Visitors whose first visit occurred in the selected period.
    filtered_new_visitors = Visitor.objects.filter(
        first_seen__date__gte=session_from_date,
        first_seen__date__lte=session_to_date,
    ).count()

    # IP traffic analysis for the selected period.
    # This is diagnostic only: it does not delete or reclassify historical data.
    # Group sessions by IP so unusually concentrated activity is visible before
    # we finalize the Estimated Human Visitors classification rules.
    ip_traffic_analysis = list(
        filtered_sessions_qs
        .exclude(ip_address__isnull=True)
        .values("ip_address")
        .annotate(
            visitor_ids=Count("visitor_id", distinct=True),
            sessions=Count("id"),
            page_views=Coalesce(Count("page_views"), 0),
            first_activity=Min("started_at"),
            last_activity=Max("started_at"),
        )
        .order_by("-sessions", "-visitor_ids")[:50]
    )

    # Classify highly concentrated bursts conservatively.
    # A source is treated as automated/suspicious when either:
    #   A) it creates >= 10 visitor IDs at an average rate of >= 1 per minute, or
    #   B) it creates >= 20 sessions at an average rate of >= 2 per minute.
    # For the management KPI, such a burst contributes 1 realistic visitor/source
    # instead of every cookie/session record being counted as a separate person.
    suspicious_ip_values = set()
    suspicious_visitor_records = 0

    for item in ip_traffic_analysis:
        first_activity = item["first_activity"]
        last_activity = item["last_activity"]
        elapsed_seconds = 1
        if first_activity and last_activity:
            elapsed_seconds = max(
                int((last_activity - first_activity).total_seconds()),
                1,
            )

        elapsed_minutes = max(elapsed_seconds / 60.0, 1 / 60.0)
        visitor_rate = item["visitor_ids"] / elapsed_minutes
        session_rate = item["sessions"] / elapsed_minutes

        is_concentrated_burst = (
            (item["visitor_ids"] >= 10 and visitor_rate >= 1.0)
            or
            (item["sessions"] >= 20 and session_rate >= 2.0)
        )

        item["elapsed_seconds"] = elapsed_seconds
        item["visitor_rate_per_minute"] = round(visitor_rate, 1)
        item["session_rate_per_minute"] = round(session_rate, 1)
        # Middle category: unusual enough to review, but not strong enough
        # to exclude from the Estimated Real Visitors KPI.
        is_review = (
            not is_concentrated_burst
            and (
                (item["sessions"] >= 10 and elapsed_minutes <= 5)
                or (item["visitor_ids"] >= 5 and elapsed_minutes <= 60)
                or (item["sessions"] >= 15)
            )
        )

        if is_concentrated_burst:
            item["traffic_classification"] = "Automated / Suspicious"
        elif is_review:
            item["traffic_classification"] = "Review"
        else:
            item["traffic_classification"] = "Normal"

        if is_concentrated_burst:
            suspicious_ip_values.add(str(item["ip_address"]))
            suspicious_visitor_records += item["visitor_ids"]

    suspicious_ip_count = len(suspicious_ip_values)

    # Each concentrated automated source contributes one realistic visitor/source.
    # Do not let the result go below zero.
    estimated_human_visitors = max(
        filtered_visitors - suspicious_visitor_records + suspicious_ip_count,
        0,
    )

    suspicious_automated = max(
        filtered_visitors - estimated_human_visitors,
        0,
    )

    # 30-day trend: apply the same realistic-visitor burst logic day by day.
    trend_start_date = today - timedelta(days=29)

    visitor_trend = []
    todays_estimated_visitors = 0
    for offset in range(30):
        day = trend_start_date + timedelta(days=offset)

        day_sessions_qs = VisitSession.objects.filter(started_at__date=day)
        day_sessions = day_sessions_qs.count()
        day_raw_visitors = (
            day_sessions_qs
            .exclude(visitor__isnull=True)
            .values("visitor_id")
            .distinct()
            .count()
        )

        day_ip_rows = list(
            day_sessions_qs
            .exclude(ip_address__isnull=True)
            .values("ip_address")
            .annotate(
                visitor_ids=Count("visitor_id", distinct=True),
                sessions=Count("id"),
                first_activity=Min("started_at"),
                last_activity=Max("started_at"),
            )
        )

        day_suspicious_visitors = 0
        day_suspicious_ips = 0

        for item in day_ip_rows:
            first_activity = item["first_activity"]
            last_activity = item["last_activity"]
            elapsed_seconds = 1
            if first_activity and last_activity:
                elapsed_seconds = max(
                    int((last_activity - first_activity).total_seconds()),
                    1,
                )

            elapsed_minutes = max(elapsed_seconds / 60.0, 1 / 60.0)
            visitor_rate = item["visitor_ids"] / elapsed_minutes
            session_rate = item["sessions"] / elapsed_minutes

            is_concentrated_burst = (
                (item["visitor_ids"] >= 10 and visitor_rate >= 1.0)
                or
                (item["sessions"] >= 20 and session_rate >= 2.0)
            )

            if is_concentrated_burst:
                day_suspicious_ips += 1
                day_suspicious_visitors += item["visitor_ids"]

        day_realistic_visitors = max(
            day_raw_visitors - day_suspicious_visitors + day_suspicious_ips,
            0,
        )

        visitor_trend.append({
            "date": day.strftime("%d %b"),
            "visitors": day_realistic_visitors,
            "sessions": day_sessions,
        })

        if day == today:
            todays_estimated_visitors = day_realistic_visitors

    # Estimated total real visitors across the complete analytics history.
    # Apply the same daily concentrated-burst rule used by the trend/KPI.
    analytics_dates = list(
        VisitSession.objects
        .dates("started_at", "day", order="ASC")
    )
    estimated_total_real_visitors = 0
    analytics_first_date = None

    for history_day_dt in analytics_dates:
        history_day = (
            history_day_dt.date()
            if hasattr(history_day_dt, "date")
            else history_day_dt
        )
        if analytics_first_date is None:
            analytics_first_date = history_day

        history_sessions_qs = VisitSession.objects.filter(
            started_at__date=history_day
        )
        history_raw_visitors = (
            history_sessions_qs
            .exclude(visitor__isnull=True)
            .values("visitor_id")
            .distinct()
            .count()
        )

        history_ip_rows = list(
            history_sessions_qs
            .exclude(ip_address__isnull=True)
            .values("ip_address")
            .annotate(
                visitor_ids=Count("visitor_id", distinct=True),
                sessions=Count("id"),
                first_activity=Min("started_at"),
                last_activity=Max("started_at"),
            )
        )

        history_suspicious_visitors = 0
        history_suspicious_ips = 0

        for item in history_ip_rows:
            first_activity = item["first_activity"]
            last_activity = item["last_activity"]
            elapsed_seconds = 1
            if first_activity and last_activity:
                elapsed_seconds = max(
                    int((last_activity - first_activity).total_seconds()),
                    1,
                )

            elapsed_minutes = max(elapsed_seconds / 60.0, 1 / 60.0)
            visitor_rate = item["visitor_ids"] / elapsed_minutes
            session_rate = item["sessions"] / elapsed_minutes

            is_concentrated_burst = (
                (item["visitor_ids"] >= 10 and visitor_rate >= 1.0)
                or
                (item["sessions"] >= 20 and session_rate >= 2.0)
            )

            if is_concentrated_burst:
                history_suspicious_ips += 1
                history_suspicious_visitors += item["visitor_ids"]

        estimated_total_real_visitors += max(
            history_raw_visitors
            - history_suspicious_visitors
            + history_suspicious_ips,
            0,
        )

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

    # Popular Pages and Devices for the selected period, excluding traffic
    # classified as Automated / Suspicious.
    estimated_real_sessions_qs = filtered_sessions_qs
    if suspicious_ip_values:
        estimated_real_sessions_qs = estimated_real_sessions_qs.exclude(
            ip_address__in=suspicious_ip_values
        )

    popular_pages = (
        PageView.objects
        .filter(session__in=estimated_real_sessions_qs)
        .values("path")
        .annotate(views=Count("id"))
        .order_by("-views")[:10]
    )

    # Device figures are distinct visitor identities, not raw sessions.
    devices = list(
        estimated_real_sessions_qs
        .values("device_type")
        .annotate(total=Count("visitor_id", distinct=True))
        .order_by("-total")
    )
    device_total = sum(item["total"] for item in devices)
    for item in devices:
        item["percentage"] = round(
            (item["total"] / device_total * 100), 1
        ) if device_total else 0

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
            "percentage": round((total / raw_total_visitors * 100), 1) if raw_total_visitors else 0,
        }
        for country_name, total in sorted(
            country_totals.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


    # ============================================================
    # SECURITY MONITORING — MONITOR ONLY
    # Uses the same selected date range as the dashboard.
    # ============================================================
    security_events_qs = SecurityRequest.objects.filter(
        occurred_at__date__range=(session_from_date, session_to_date)
    )

    security_event_count = security_events_qs.count()
    security_review_count = security_events_qs.filter(risk_level="review").count()
    security_potential_threat_count = security_events_qs.filter(
        risk_level="potential_threat"
    ).count()
    security_high_risk_count = security_events_qs.filter(risk_level="high").count()

    security_ip_values = list(
        security_events_qs.exclude(ip_address__isnull=True)
        .values_list("ip_address", flat=True)
    )
    security_ips_monitored = len({
        str(ip).strip() for ip in security_ip_values if str(ip).strip()
    })

    latest_security_activity = list(
        security_events_qs.order_by("-occurred_at")[:100]
    )

    context = {
        "total_visitors": estimated_total_real_visitors,
        "raw_total_visitors": raw_total_visitors,
        "analytics_first_date": analytics_first_date,
        "analytics_last_date": today,
        "total_sessions": total_sessions,
        "unique_ips": unique_ips,
        "total_page_views": total_page_views,
        "todays_visitors": todays_estimated_visitors,
        "total_subscribers": total_subscribers,
        "visitor_trend": visitor_trend,
        "recent_subscribers": recent_subscribers,
        "recent_sessions": recent_sessions,
        "popular_pages": popular_pages,
        "devices": devices,
        "browsers": browsers,
        "operating_systems": operating_systems,
        "countries": countries,

        # Security monitoring.
        "security_event_count": security_event_count,
        "security_ips_monitored": security_ips_monitored,
        "security_review_count": security_review_count,
        "security_potential_threat_count": security_potential_threat_count,
        "security_high_risk_count": security_high_risk_count,
        "latest_security_activity": latest_security_activity,

        # Date-filter context.
        "filter_from_date": session_from_date.strftime("%Y-%m-%d"),
        "filter_to_date": session_to_date.strftime("%Y-%m-%d"),
        "has_date_filter": has_date_filter,
        "filtered_session_count": filtered_session_count,
        "filtered_visitors": filtered_visitors,
        "suspicious_visitor_count": suspicious_visitor_count,
        "suspicious_ips": sorted(suspicious_ips),
        "filtered_unique_ips": filtered_unique_ips,
        "filtered_page_views": filtered_page_views,
        "filtered_new_visitors": filtered_new_visitors,
        "estimated_human_visitors": estimated_human_visitors,
        "suspicious_automated": suspicious_automated,
        "suspicious_ip_count": suspicious_ip_count,
        "ip_traffic_analysis": ip_traffic_analysis,
        "today_iso": today.strftime("%Y-%m-%d"),
        "yesterday_iso": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
        "last7_iso": (today - timedelta(days=6)).strftime("%Y-%m-%d"),
        "last30_iso": (today - timedelta(days=29)).strftime("%Y-%m-%d"),
    }

    return render(request, "analytics/dashboard.html", context)
