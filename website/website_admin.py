from django.contrib import admin

from .website_models import (
    LearningContent,
    QuestionBank,
    QuizExam,
    QuizExamQuestion,
    QuestionAIExplanation,
)


@admin.register(LearningContent)
class LearningContentAdmin(admin.ModelAdmin):
    list_display = (
        "id", "category", "certification", "content_type",
        "title", "topic", "status", "updated_at",
    )
    list_filter = ("category", "certification", "content_type", "status")
    search_fields = ("title", "topic", "content", "source_reference")
    ordering = ("category", "certification", "sort_order", "id")


@admin.register(QuestionBank)
class QuestionBankAdmin(admin.ModelAdmin):
    list_display = (
        "id", "certification", "question_type", "question_format",
        "domain", "topic", "difficulty", "correct_answer",
        "status", "is_active", "updated_at",
    )
    list_filter = (
        "category", "certification", "question_type", "question_format",
        "domain", "difficulty", "source_type", "status", "is_active",
    )
    search_fields = (
        "question_text", "domain", "topic",
        "source_question_id", "source_reference",
    )
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Classification", {
            "fields": (
                "category", "certification", "question_type",
                "question_format", "domain", "topic", "difficulty",
            )
        }),
        ("Question", {
            "fields": (
                "question_text",
                "option_a", "option_b", "option_c", "option_d",
                "correct_answer",
            )
        }),
        ("Explanation", {
            "fields": (
                "source_explanation",
                "thestoreware_explanation",
                "exam_tip",
            )
        }),
        ("Source / Traceability", {
            "fields": (
                "source_type",
                "source_reference",
                "source_question_id",
            )
        }),
        ("Publishing", {
            "fields": ("status", "is_active", "created_at", "updated_at")
        }),
    )


class QuizExamQuestionInline(admin.TabularInline):
    model = QuizExamQuestion
    extra = 1
    autocomplete_fields = ("question",)


@admin.register(QuizExam)
class QuizExamAdmin(admin.ModelAdmin):
    list_display = (
        "id", "certification", "title", "quiz_type",
        "duration_minutes", "passing_score", "status", "is_active",
    )
    list_filter = ("category", "certification", "quiz_type", "status", "is_active")
    search_fields = ("title", "description", "slug")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (QuizExamQuestionInline,)


@admin.register(QuizExamQuestion)
class QuizExamQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "quiz_exam", "question", "sort_order", "points")
    list_filter = ("quiz_exam",)
    search_fields = ("quiz_exam__title", "question__question_text")
    autocomplete_fields = ("quiz_exam", "question")


@admin.register(QuestionAIExplanation)
class QuestionAIExplanationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "question", "language", "version",
        "review_status", "accuracy_verified",
        "video_status", "updated_at",
    )
    list_filter = (
        "language", "review_status", "accuracy_verified",
        "video_status", "ai_provider",
    )
    search_fields = (
        "question__question_text",
        "explanation_text",
        "short_summary",
        "key_learning_point",
        "video_script",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("question",)
