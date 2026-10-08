import uuid

from django.db.models import F
from django.utils import timezone

from .models import Visitor, VisitSession, PageView


class AnalyticsMiddleware:

    VISITOR_COOKIE = "tsw_visitor_id"
    SESSION_KEY = "tsw_analytics_session_id"

    # 1 year
    COOKIE_MAX_AGE = 60 * 60 * 24 * 365

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # ---------------------------------------------
        # Do not track technical/internal requests
        # ---------------------------------------------
        excluded_paths = (
            "/admin",
            "/static",
            "/favicon.ico",
            "/robots.txt",
            "/.well-known",
            "/analytics",
        )

        # Track only normal GET page requests.
        # Exclude admin, static/technical requests and the analytics dashboard itself.
        if (
            request.method != "GET"
            or request.path.lower().startswith(excluded_paths)
        ):
            return self.get_response(request)

        visitor = None
        visit_session = None
        new_visitor_id = None

        try:

            # =============================================
            # 1. BASIC REQUEST INFORMATION
            # =============================================

            language = request.META.get(
                "HTTP_ACCEPT_LANGUAGE", ""
            )[:20]

            referrer = request.META.get(
                "HTTP_REFERER", ""
            )

            user_agent = request.META.get(
                "HTTP_USER_AGENT", ""
            ).lower()

            # =============================================
            # 2. SIMPLE DEVICE DETECTION
            # =============================================

            if "mobile" in user_agent:
                device_type = "Mobile"
            elif "tablet" in user_agent or "ipad" in user_agent:
                device_type = "Tablet"
            else:
                device_type = "Desktop"

            # =============================================
            # 3. SIMPLE BROWSER DETECTION
            # =============================================

            if "edg/" in user_agent:
                browser = "Edge"
            elif "chrome/" in user_agent:
                browser = "Chrome"
            elif "firefox/" in user_agent:
                browser = "Firefox"
            elif "safari/" in user_agent:
                browser = "Safari"
            else:
                browser = "Other"

            # =============================================
            # 4. SIMPLE OPERATING SYSTEM DETECTION
            # =============================================

            if "windows" in user_agent:
                operating_system = "Windows"
            elif "android" in user_agent:
                operating_system = "Android"
            elif "iphone" in user_agent or "ipad" in user_agent:
                operating_system = "iOS"
            elif "mac os" in user_agent:
                operating_system = "macOS"
            elif "linux" in user_agent:
                operating_system = "Linux"
            else:
                operating_system = "Other"

            # =============================================
            # 5. IDENTIFY VISITOR
            # =============================================

            visitor_id = request.COOKIES.get(
                self.VISITOR_COOKIE
            )

            if visitor_id:

                try:
                    visitor = Visitor.objects.get(
                        visitor_id=visitor_id
                    )

                    # auto_now updates last_seen
                    visitor.save()

                except Visitor.DoesNotExist:
                    visitor = None

            if visitor is None:

                new_visitor_id = str(uuid.uuid4())

                visitor = Visitor.objects.create(
                    visitor_id=new_visitor_id,
                    first_language=language,
                    first_referrer=referrer,
                )

            # =============================================
            # 6. IDENTIFY / CREATE VISIT SESSION
            # =============================================

            analytics_session_id = request.session.get(
                self.SESSION_KEY
            )

            if analytics_session_id:

                try:
                    visit_session = VisitSession.objects.get(
                        session_id=analytics_session_id,
                        visitor=visitor,
                    )

                except VisitSession.DoesNotExist:
                    visit_session = None

            if visit_session is None:

                analytics_session_id = str(uuid.uuid4())

                visit_session = VisitSession.objects.create(
                    visitor=visitor,
                    session_id=analytics_session_id,
                    entry_page=request.path,
                    exit_page=request.path,
                    referrer=referrer,
                    language=language,
                    device_type=device_type,
                    browser=browser,
                    operating_system=operating_system,
                    page_view_count=0,
                )

                request.session[
                    self.SESSION_KEY
                ] = analytics_session_id

                # Increase total visit/session count
                Visitor.objects.filter(
                    pk=visitor.pk
                ).update(
                    visit_count=F("visit_count") + 1
                )

            else:

                visit_session.exit_page = request.path
                visit_session.save()

            # =============================================
            # 7. CREATE PAGE VIEW
            # =============================================

            PageView.objects.create(
                session=visit_session,
                path=request.path,
                referrer=referrer,
                language=language,
            )

            # =============================================
            # 8. UPDATE PAGE VIEW COUNTER
            # =============================================

            VisitSession.objects.filter(
                pk=visit_session.pk
            ).update(
                page_view_count=F("page_view_count") + 1
            )

        except Exception as exc:

            # Analytics must never break the public website.
            print(
                f"TheStoreWare Analytics Error: {exc}"
            )

        # =============================================
        # NORMAL WEBSITE RESPONSE
        # =============================================

        response = self.get_response(request)

        # =============================================
        # 9. SAVE ANONYMOUS VISITOR COOKIE
        # =============================================

        if new_visitor_id:

            response.set_cookie(
                self.VISITOR_COOKIE,
                new_visitor_id,
                max_age=self.COOKIE_MAX_AGE,
                httponly=True,
                secure=request.is_secure(),
                samesite="Lax",
            )

        return response