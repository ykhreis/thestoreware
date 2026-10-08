from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from .models import Visitor, VisitSession, PageView


def dashboard(request):
    today = timezone.localdate()

    total_visitors = Visitor.objects.count()
    total_sessions = VisitSession.objects.count()
    total_page_views = PageView.objects.count()
    todays_visitors = Visitor.objects.filter(first_seen__date=today).count()

    popular_pages = (
        PageView.objects
        .values('path')
        .annotate(views=Count('id'))
        .order_by('-views')[:10]
    )

    browsers = (
        VisitSession.objects
        .values('browser')
        .annotate(total=Count('id'))
        .order_by('-total')
    )

    devices = (
        VisitSession.objects
        .values('device_type')
        .annotate(total=Count('id'))
        .order_by('-total')
    )

    operating_systems = (
        VisitSession.objects
        .values('operating_system')
        .annotate(total=Count('id'))
        .order_by('-total')
    )

    recent_sessions = (
        VisitSession.objects
        .select_related('visitor')
        .order_by('-last_activity')[:10]
    )

    context = {
        'total_visitors': total_visitors,
        'total_sessions': total_sessions,
        'total_page_views': total_page_views,
        'todays_visitors': todays_visitors,
        'popular_pages': popular_pages,
        'browsers': browsers,
        'devices': devices,
        'operating_systems': operating_systems,
        'recent_sessions': recent_sessions,
    }

    return render(request, 'analytics/dashboard.html', context)
