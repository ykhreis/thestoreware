from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .website_models import WebsiteUserFeedback


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
            sent_count = send_mail(
                subject,
                body,
                getattr(settings, "DEFAULT_FROM_EMAIL", notification_email),
                [notification_email],
                fail_silently=False,
            )

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

    return redirect(reverse("home") + "?feedback=success#feedback")
