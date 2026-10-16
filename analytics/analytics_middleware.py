import hashlib
import uuid

from django.conf import settings
from django.contrib.gis.geoip2 import GeoIP2

from django.db.models import F
from django.utils import timezone

from .analytics_models import Visitor, VisitSession, PageView, SecurityRequest


class AnalyticsMiddleware:

    VISITOR_COOKIE = "tsw_visitor_id"
    SESSION_KEY = "tsw_analytics_session_id"

    # 1 year
    COOKIE_MAX_AGE = 60 * 60 * 24 * 365

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _get_client_ip(request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "").strip() or None

    @staticmethod
    def _hash_ip(ip_address):
        if not ip_address:
            return ""
        value = f"{settings.SECRET_KEY}:{ip_address}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _get_ip_location(ip_address):
        """Resolve an approximate location using a local GeoIP database.

        No external API call is made. If GeoIP is not configured, the IP is
        private/local, or lookup fails, analytics continues with blank location.
        """
        if not ip_address:
            return {"country_code": "", "country_name": "", "region": "", "city": ""}

        try:
            import ipaddress
            ip_obj = ipaddress.ip_address(ip_address)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
                return {
                    "country_code": "",
                    "country_name": "Local / Development",
                    "region": "",
                    "city": "",
                }

            geo = GeoIP2()
            data = geo.city(ip_address)
            return {
                "country_code": (data.get("country_code") or "")[:2],
                "country_name": (data.get("country_name") or "")[:100],
                "region": (data.get("region") or "")[:120],
                "city": (data.get("city") or "")[:120],
            }
        except Exception:
            return {"country_code": "", "country_name": "", "region": "", "city": ""}

    @staticmethod
    def _security_risk(path, method, status_code):
        """
        Conservative monitoring-only classification.
        A suspicious-looking path is evidence for review, not proof of an attack.
        """
        path_lower = (path or "").lower()

        high_interest_tokens = (
            "/.env",
            "/wp-admin",
            "/wp-login",
            "/phpmyadmin",
            "/administrator",
            "/config.php",
            "/server-status",
            "/.git",
            "/vendor/phpunit",
            "/cgi-bin",
        )

        sensitive_tokens = (
            "/admin",
            "/login",
            "/accounts/login",
        )

        if any(token in path_lower for token in high_interest_tokens):
            return "potential_threat", "Probe for a sensitive or unrelated application path"

        if method not in ("GET", "HEAD", "POST"):
            return "review", f"Unusual HTTP method: {method}"

        if status_code in (401, 403) and any(token in path_lower for token in sensitive_tokens):
            return "review", "Denied request to an authentication/administration path"

        if status_code == 404:
            return "review", "Request returned 404 Not Found"

        return "low", ""

    def _record_security_request(self, request, response):
        """
        Record security-relevant evidence separately from normal analytics.
        This function never blocks the request and failures never affect the site.
        """
        try:
            client_ip = self._get_client_ip(request)
            method = (request.method or "")[:10]
            path = (request.path or "")[:2000]
            status_code = getattr(response, "status_code", None)
            user_agent = request.META.get("HTTP_USER_AGENT", "")[:2000]

            risk_level, risk_reason = self._security_risk(
                path,
                method,
                status_code,
            )

            # Keep the first version focused: record abnormal responses,
            # suspicious paths/methods, and admin/authentication activity.
            should_record = (
                risk_level != "low"
                or status_code in (400, 401, 403, 404, 405, 429, 500, 502, 503)
                or path.lower().startswith(("/admin", "/login", "/accounts/"))
            )

            if should_record:
                SecurityRequest.objects.create(
                    ip_address=client_ip,
                    ip_hash=self._hash_ip(client_ip),
                    method=method,
                    path=path,
                    status_code=status_code,
                    user_agent=user_agent,
                    risk_level=risk_level,
                    risk_reason=risk_reason,
                )
        except Exception as exc:
            print(f"TheStoreWare Security Monitor Error: {exc}")

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
            response = self.get_response(request)
            self._record_security_request(request, response)
            return response

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

            client_ip = self._get_client_ip(request)
            client_ip_hash = self._hash_ip(client_ip)
            ip_location = self._get_ip_location(client_ip)

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

                    visitor.last_ip_address = client_ip
                    visitor.ip_hash = client_ip_hash
                    visitor.save(
                        update_fields=["last_ip_address", "ip_hash", "last_seen"]
                    )

                except Visitor.DoesNotExist:
                    visitor = None

            if visitor is None:

                new_visitor_id = str(uuid.uuid4())

                visitor = Visitor.objects.create(
                    visitor_id=new_visitor_id,
                    first_language=language,
                    first_referrer=referrer,
                    first_ip_address=client_ip,
                    last_ip_address=client_ip,
                    ip_hash=client_ip_hash,
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
                    ip_address=client_ip,
                    country_code=ip_location["country_code"],
                    country_name=ip_location["country_name"],
                    region=ip_location["region"],
                    city=ip_location["city"],
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

                # Refresh network/location information on every normal page visit.
                # This also backfills sessions created before these fields existed.
                visit_session.exit_page = request.path
                visit_session.ip_address = client_ip
                visit_session.country_code = ip_location["country_code"]
                visit_session.country_name = ip_location["country_name"]
                visit_session.region = ip_location["region"]
                visit_session.city = ip_location["city"]
                visit_session.save(
                    update_fields=[
                        "exit_page",
                        "ip_address",
                        "country_code",
                        "country_name",
                        "region",
                        "city",
                        "last_activity",
                    ]
                )

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
        # SECURITY MONITORING (MONITOR ONLY)
        # =============================================
        self._record_security_request(request, response)

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