from django.urls import path
from . import website_views

urlpatterns = [
    path("", website_views.home, name="home"),
    path("sitemap.xml", website_views.sitemap_xml, name="sitemap"),
    path("robots.txt", website_views.robots_txt, name="robots_txt"),
    path("area/<slug:slug>/", website_views.area_detail, name="area_detail"),

    path("courses/", website_views.courses, name="courses"),

    path("exams-quizzes/", website_views.exams_quizzes, name="exams_quizzes"),
    path(
        "quiz/<int:quiz_id>/",
        website_views.exam_quiz_start,
        name="exam_quiz_start",
    ),
    path(
        "exams-quizzes/<slug:area_slug>/<slug:certification_slug>/",
        website_views.exam_certification,
        name="exam_certification",
    ),
    path(
        "exams-quizzes/<slug:area_slug>/",
        website_views.exam_area,
        name="exam_area",
    ),

    path(
        "content-management/",
        website_views.content_management,
        name="content_management",
    ),
    path(
        "content-management/seo-monitoring/",
        website_views.seo_monitoring,
        name="seo_monitoring",
    ),
    path(
        "content-management/youtube-extractor/",
        website_views.youtube_extractor,
        name="youtube_extractor",
    ),
    path(
        "content-management/youtube-extractor/scan/start/",
        website_views.youtube_scan_start,
        name="youtube_scan_start",
    ),
    path(
        "content-management/youtube-extractor/scan/status/<str:job_id>/",
        website_views.youtube_scan_status,
        name="youtube_scan_status",
    ),
    path(
        "content-management/youtube-extractor/scan/stop/<str:job_id>/",
        website_views.youtube_scan_stop,
        name="youtube_scan_stop",
    ),
    path(
        "content-management/courses/",
        website_views.courses_management,
        name="courses_management",
    ),
    path(
        "content-management/questions-answers/",
        website_views.exam_quiz_management,
        name="exam_quiz_management",
    ),
    path(
        "content-management/questions-answers/import/",
        website_views.quiz_question_import,
        name="quiz_question_import",
    ),
    path(
        "content-management/questions-answers/export/",
        website_views.question_bank_export,
        name="question_bank_export",
    ),
    path(
        "content-management/questions-answers/generator/",
        website_views.quiz_exam_generator,
        name="quiz_exam_generator",
    ),

    path("feedback/", website_views.submit_feedback, name="submit_feedback"),
    path("ai/chat/", website_views.chatbot_ask, name="chatbot_ask"),
    path("subscribe/", website_views.subscribe, name="subscribe"),
    path(
        "subscribe/profile/",
        website_views.subscribe_profile,
        name="subscribe_profile",
    ),
]
