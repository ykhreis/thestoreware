from django.conf import settings
from django.core.mail import EmailMessage, get_connection, send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .website_models import WebsiteSubscriber, WebsiteUserFeedback


def get_thestoreware_email_connection():
    """Return a dedicated Microsoft 365 SMTP connection for TheStoreWare."""
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=getattr(settings, "THESTOREWARE_EMAIL_HOST", "smtp.office365.com"),
        port=getattr(settings, "THESTOREWARE_EMAIL_PORT", 587),
        username=getattr(settings, "THESTOREWARE_EMAIL_USER", ""),
        password=getattr(settings, "THESTOREWARE_EMAIL_PASSWORD", ""),
        use_tls=getattr(settings, "THESTOREWARE_EMAIL_USE_TLS", True),
        fail_silently=False,
    )


def send_thestoreware_acknowledgement(name, recipient_email):
    """Send an automatic acknowledgement from info@thestoreware.com."""
    if not recipient_email:
        return

    from_email = getattr(settings, "THESTOREWARE_EMAIL_USER", "").strip()
    if not from_email:
        raise ValueError("THESTOREWARE_EMAIL_USER is not configured.")

    greeting = f"Dear {name}," if name else "Hello,"
    body = (
        f"{greeting}\n\n"
        "Thank you for contacting TheStoreWare.\n\n"
        "We have received your message successfully and appreciate your feedback. "
        "Our team will review it and get back to you if a response is required.\n\n"
        "Best regards,\n"
        "TheStoreWare Team\n"
        "info@thestoreware.com"
    )

    connection = get_thestoreware_email_connection()
    email_message = EmailMessage(
        subject="Thank you for contacting TheStoreWare",
        body=body,
        from_email=from_email,
        to=[recipient_email],
        connection=connection,
    )
    email_message.send(fail_silently=False)


AREAS = [
    {
        "slug": "ai-agent", "title": "AI-Agent", "icon": "AI", "art_class": "art-ai",
        "status": "Available Now",
        "summary": "Ask, analyze, understand and interact with knowledge.",
        "description": "An intelligent knowledge experience designed to understand questions, analyze information and reuse trusted knowledge.",
        "topics": ["Ask AI", "Document Understanding", "Knowledge Search", "Multilingual", "Voice", "Source Trace"],
    },
    {
        "slug": "courses", "title": "Courses", "icon": "EDU", "art_class": "art-courses",
        "status": "Coming Soon",
        "summary": "Learn through practical, structured and interactive content.",
        "description": "A growing learning area for professional, technology and general-interest subjects.",
        "topics": ["Project Management", "AI", "Technology", "Cybersecurity", "Business", "More Topics"],
    },
    {
        "slug": "exams-quizzes", "title": "Exams & Quizzes", "icon": "Q", "art_class": "art-exams",
        "status": "Coming Soon",
        "summary": "Practice, test yourself and understand every answer.",
        "description": "Interactive practice, question banks and smart quizzes designed for learning rather than memorization.",
        "topics": ["Practice Exams", "Smart Quizzes", "Explanations", "Progress", "Question Banks", "Challenges"],
    },
    {
        "slug": "professional", "title": "Professional", "icon": "PRO", "art_class": "art-professional",
        "status": "Coming Soon",
        "summary": "Practical knowledge for work, projects and technology.",
        "description": "Professional knowledge designed to turn experience and standards into useful, practical learning.",
        "topics": ["Project Management", "Technology", "AI", "Cybersecurity", "Business", "Professional Skills"],
    },
    {
        "slug": "entertainment", "title": "Entertainment & Discovery", "icon": "360°", "art_class": "art-entertainment",
        "status": "Coming Soon",
        "summary": "Discover the world through knowledge, facts and challenges.",
        "description": "Explore fascinating subjects through informative pages, questions, challenges and AI-assisted discovery.",
        "topics": ["History", "Geography", "Science", "Geology", "Space", "Civilizations", "Religions", "General Knowledge"],
    },
    {
        "slug": "knowledge-hub", "title": "Knowledge Hub", "icon": "K", "art_class": "art-knowledge",
        "status": "Coming Soon",
        "summary": "Articles, guides, explanations and useful information.",
        "description": "A structured library of useful information that can be explored, understood and reused.",
        "topics": ["Articles", "Guides", "Explanations", "What's New", "Popular Topics", "Learning"],
    },
    {
        "slug": "smart-tools", "title": "Smart Tools", "icon": "TOOLS", "art_class": "art-tools",
        "status": "Coming Soon",
        "summary": "Useful document, PDF, image and file utilities.",
        "description": "Simple everyday utilities plus intelligent tools where AI adds real value.",
        "topics": ["Word → PDF", "PDF Tools", "Image Resize", "Image Enhancement", "File Compression", "Text Tools"],
    },
    {
        "slug": "ai-lab", "title": "AI Lab", "icon": "LAB", "art_class": "art-lab",
        "status": "Coming Soon",
        "summary": "Explore new AI ideas, experiments and capabilities.",
        "description": "A space for testing new ways AI can help people learn, create, understand and solve problems.",
        "topics": ["Experiments", "AI Demos", "New Features", "Prototypes", "Ideas", "Future Capabilities"],
    },
]


def home(request):
    return render(
        request,
        "website/website_home.html",
        {
            "areas": AREAS,
            "feedback_success": request.GET.get("feedback") == "success",
        },
    )


def area_detail(request, slug):
    area = next((item for item in AREAS if item["slug"] == slug), None)
    if area is None:
        from django.http import Http404
        raise Http404("Area not found")
    return render(request, "website/website_area_detail.html", {"area": area})


def submit_feedback(request):
    if request.method != "POST":
        return redirect(reverse("home") + "#feedback")

    category = request.POST.get("category", "").strip()
    message = request.POST.get("message", "").strip()
    name = request.POST.get("name", "").strip()
    email = request.POST.get("email", "").strip()

    if not category or not message:
        return render(
            request,
            "website/website_home.html",
            {
                "areas": AREAS,
                "feedback_error": "Please select a category and enter your idea or feedback.",
            },
            status=400,
        )

    feedback = WebsiteUserFeedback.objects.create(
        category=category,
        message=message,
        name=name,
        email=email,
    )

    notification_email = getattr(settings, "FEEDBACK_NOTIFICATION_EMAIL", "").strip()

    if notification_email:
        subject = f"New TheStoreWare Feedback — {category}"
        body = (
            f"A new idea/feedback was submitted to TheStoreWare.\n\n"
            f"Category: {category}\n"
            f"Name: {name or 'Not provided'}\n"
            f"Email: {email or 'Not provided'}\n\n"
            f"Feedback:\n{message}\n\n"
            f"Feedback ID: {feedback.pk}"
        )

        try:
            # Send the internal notification through the dedicated
            # TheStoreWare Microsoft 365 mailbox (info@thestoreware.com).
            from_email = getattr(settings, "THESTOREWARE_EMAIL_USER", "").strip()
            if not from_email:
                raise ValueError("THESTOREWARE_EMAIL_USER is not configured.")

            connection = get_thestoreware_email_connection()
            # Send the internal notification to both TheStoreWare
            # and the existing Gmail notification address.
            notification_recipients = [
                address
                for address in [from_email, notification_email]
                if address
            ]
            # Avoid sending twice if both settings contain the same address.
            notification_recipients = list(dict.fromkeys(notification_recipients))

            notification_message = EmailMessage(
                subject=subject,
                body=body,
                from_email=from_email,
                to=notification_recipients,
                reply_to=[email] if email else None,
                connection=connection,
            )
            sent_count = notification_message.send(fail_silently=False)

            if sent_count == 1:
                feedback.notification_sent = True
                feedback.notification_sent_at = timezone.now()
                feedback.notification_error = ""
            else:
                feedback.notification_sent = False
                feedback.notification_error = (
                    "Email backend returned 0 messages sent."
                )

        except Exception as exc:
            # The feedback remains safely stored even if email notification fails.
            feedback.notification_sent = False
            feedback.notification_error = str(exc)[:2000]

        feedback.save(
            update_fields=[
                "notification_sent",
                "notification_sent_at",
                "notification_error",
            ]
        )
    else:
        feedback.notification_sent = False
        feedback.notification_error = (
            "FEEDBACK_NOTIFICATION_EMAIL is not configured."
        )
        feedback.save(
            update_fields=[
                "notification_sent",
                "notification_error",
            ]
        )

    # Send a separate acknowledgement to the visitor using the
    # TheStoreWare Microsoft 365 mailbox. A failure here must never
    # prevent the already-stored feedback from being accepted.
    if email:
        try:
            send_thestoreware_acknowledgement(name, email)
        except Exception:
            pass

    return redirect(reverse("home") + "?feedback=success#feedback")

def _current_analytics_links(request):
    """Return the current analytics Visitor and VisitSession when available."""
    visitor = None
    visit_session = None
    visitor_id = request.COOKIES.get("tsw_visitor_id")
    analytics_session_id = request.session.get("tsw_analytics_session_id")

    try:
        from analytics.analytics_models import Visitor, VisitSession

        if visitor_id:
            visitor = Visitor.objects.filter(visitor_id=visitor_id).first()

        if analytics_session_id:
            visit_session = VisitSession.objects.filter(
                session_id=analytics_session_id
            ).first()
            if visit_session is not None:
                visitor = visit_session.visitor
    except Exception:
        # Subscription/profile must remain available even if analytics linking fails.
        visitor = None
        visit_session = None

    return visitor, visit_session


def subscribe(request):
    """
    Footer entry point.
    Validate the mandatory email, then send the visitor to the full
    subscription profile page with the email pre-filled.
    """
    if request.method != "POST":
        return redirect(reverse("home") + "#subscribe")

    email = request.POST.get("email", "").strip().lower()

    try:
        validate_email(email)
    except ValidationError:
        return redirect(reverse("home") + "?subscribe=invalid#subscribe")

    return redirect(reverse("subscribe_profile") + f"?email={email}")


def subscribe_profile(request):
    """Display and save the optional TheStoreWare subscriber profile."""
    initial_email = request.GET.get("email", "").strip().lower()

    if request.method == "GET":
        return render(
            request,
            "website/website_subscribe.html",
            {
                "subscriber_email": initial_email,
            },
        )

    email = request.POST.get("email", "").strip().lower()
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    country = request.POST.get("country", "").strip()
    mobile_number = request.POST.get("mobile_number", "").strip()
    preferred_language = request.POST.get("preferred_language", "").strip()
    company_organization = request.POST.get("company_organization", "").strip()
    job_title = request.POST.get("job_title", "").strip()
    areas_of_interest = request.POST.get("areas_of_interest", "").strip()
    consent_to_updates = request.POST.get("consent_to_updates") == "on"

    form_values = {
        "subscriber_email": email,
        "first_name": first_name,
        "last_name": last_name,
        "country": country,
        "mobile_number": mobile_number,
        "preferred_language": preferred_language,
        "company_organization": company_organization,
        "job_title": job_title,
        "areas_of_interest": areas_of_interest,
        "consent_to_updates": consent_to_updates,
    }

    try:
        validate_email(email)
    except ValidationError:
        form_values["subscribe_error"] = "Please enter a valid email address."
        return render(
            request,
            "website/website_subscribe.html",
            form_values,
            status=400,
        )

    if not consent_to_updates:
        form_values["subscribe_error"] = (
            "Please confirm that you agree to receive updates from TheStoreWare."
        )
        return render(
            request,
            "website/website_subscribe.html",
            form_values,
            status=400,
        )

    visitor, visit_session = _current_analytics_links(request)

    subscriber, created = WebsiteSubscriber.objects.get_or_create(email=email)

    subscriber.first_name = first_name
    subscriber.last_name = last_name
    subscriber.country = country
    subscriber.mobile_number = mobile_number
    subscriber.preferred_language = preferred_language
    subscriber.company_organization = company_organization
    subscriber.job_title = job_title
    subscriber.areas_of_interest = areas_of_interest
    subscriber.consent_to_updates = True
    subscriber.consent_at = timezone.now()
    subscriber.visitor = visitor
    subscriber.visit_session = visit_session
    subscriber.is_active = True
    subscriber.unsubscribed_at = None
    subscriber.source = "website_footer"
    subscriber.save()

    return render(
        request,
        "website/website_subscribe.html",
        {
            "subscriber_email": subscriber.email,
            "subscribe_success": True,
            "subscriber_created": created,
        },
    )
