from django.urls import path
from . import website_views

urlpatterns = [
    path("", website_views.home, name="home"),
    path("sitemap.xml", website_views.sitemap_xml, name="sitemap"),
    path("robots.txt", website_views.robots_txt, name="robots_txt"),
    path("area/<slug:slug>/", website_views.area_detail, name="area_detail"),
    path("courses/", website_views.courses, name="courses"),
    path("exams-quizzes/", website_views.exams_quizzes, name="exams_quizzes"),
    path("exams-quizzes/import-questions/", website_views.quiz_question_import, name="quiz_question_import"),
    path("exams-quizzes/quiz/<int:quiz_id>/", website_views.exam_quiz_start, name="exam_quiz_start"),
    path("exams-quizzes/<slug:area_slug>/", website_views.exam_area, name="exam_area"),
    path("content-management/", website_views.content_management, name="content_management"),
    path("content-management/courses/", website_views.courses_management, name="courses_management"),
    path("content-management/exams-quizzes/", website_views.exam_quiz_management, name="exam_quiz_management"),
    path("feedback/", website_views.submit_feedback, name="submit_feedback"),
    path("ai/chat/", website_views.chatbot_ask, name="chatbot_ask"),
    path("subscribe/", website_views.subscribe, name="subscribe"),
    path("subscribe/profile/", website_views.subscribe_profile, name="subscribe_profile"),
]
