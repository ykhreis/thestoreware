from django.db import models


class WebsiteUserFeedback(models.Model):

    STATUS_CHOICES = [
        ("new", "New"),
        ("reviewed", "Reviewed"),
        ("planned", "Planned"),
        ("implemented", "Implemented"),
    ]

    # Feedback information
    category = models.CharField(max_length=80)
    message = models.TextField(max_length=4000)
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)

    # Feedback lifecycle
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="new",
        db_index=True,
    )

    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Email notification audit
    notification_sent = models.BooleanField(default=False)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    notification_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.category} - {self.submitted_at:%Y-%m-%d %H:%M}"

class WebsiteSubscriber(models.Model):
    LANGUAGE_CHOICES = [
        ("", "Not specified"),
        ("en", "English"),
        ("ar", "Arabic"),
        ("fr", "French"),
        ("other", "Other"),
    ]

    # Mandatory subscription identity
    email = models.EmailField(unique=True, db_index=True)

    # Optional subscriber profile
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=100, blank=True)
    mobile_number = models.CharField(max_length=40, blank=True)
    preferred_language = models.CharField(
        max_length=20,
        choices=LANGUAGE_CHOICES,
        blank=True,
    )
    company_organization = models.CharField(max_length=180, blank=True)
    job_title = models.CharField(max_length=150, blank=True)
    areas_of_interest = models.TextField(blank=True)

    # Explicit permission to receive TheStoreWare updates
    consent_to_updates = models.BooleanField(default=False)
    consent_at = models.DateTimeField(null=True, blank=True)

    # Link to the existing anonymous analytics records.
    visitor = models.ForeignKey(
        "analytics.Visitor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="website_subscriptions",
    )
    visit_session = models.ForeignKey(
        "analytics.VisitSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="website_subscriptions",
    )

    # Subscription lifecycle
    is_active = models.BooleanField(default=True, db_index=True)
    source = models.CharField(max_length=50, default="website_footer")
    subscribed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-subscribed_at"]

    def __str__(self):
        return self.email

# ============================================================
# TheStoreWare Learning / Courses / Quiz & Exam metadata
# ============================================================

class LearningContent(models.Model):
    CONTENT_TYPE_CHOICES = [
        ("course", "Course"),
        ("lesson", "Lesson"),
        ("concept", "Concept"),
        ("study_note", "Study Note"),
        ("video_script", "Video Script"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("reviewed", "Reviewed"),
        ("approved", "Approved"),
        ("published", "Published"),
        ("archived", "Archived"),
    ]

    category = models.CharField(max_length=100, db_index=True)
    certification = models.CharField(max_length=80, blank=True, db_index=True)
    content_type = models.CharField(max_length=30, choices=CONTENT_TYPE_CHOICES, db_index=True)
    title = models.CharField(max_length=250)
    topic = models.CharField(max_length=180, blank=True, db_index=True)
    content = models.TextField()
    source_type = models.CharField(max_length=30, blank=True)
    source_reference = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "certification", "sort_order", "id"]

    def __str__(self):
        return f"{self.certification or self.category} - {self.title}"


class QuestionBank(models.Model):
    QUESTION_FORMAT_CHOICES = [
        ("single_choice", "Single Choice"),
        ("multiple_choice", "Multiple Choice"),
        ("true_false", "True / False"),
    ]
    QUESTION_TYPE_CHOICES = [
        ("practice", "Practice"),
        ("quiz", "Quiz"),
        ("mini_exam", "Mini Exam"),
        ("mock_exam", "Mock Exam"),
        ("knowledge_check", "Knowledge Check"),
    ]
    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
        ("not_set", "Not Set"),
    ]
    SOURCE_TYPE_CHOICES = [
        ("screenshot", "Screenshot"),
        ("pdf", "PDF"),
        ("video", "Video"),
        ("manual", "Manual"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("reviewed", "Reviewed"),
        ("approved", "Approved"),
        ("published", "Published"),
        ("archived", "Archived"),
    ]

    # Classification metadata
    category = models.CharField(max_length=100, db_index=True)
    certification = models.CharField(max_length=80, blank=True, db_index=True)
    question_type = models.CharField(max_length=30, choices=QUESTION_TYPE_CHOICES, default="practice", db_index=True)
    question_format = models.CharField(max_length=30, choices=QUESTION_FORMAT_CHOICES, default="single_choice", db_index=True)
    domain = models.CharField(max_length=180, blank=True, db_index=True)
    topic = models.CharField(max_length=180, blank=True, db_index=True)
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default="not_set", db_index=True)

    # Question and choices
    question_text = models.TextField()
    option_a = models.TextField(blank=True)
    option_b = models.TextField(blank=True)
    option_c = models.TextField(blank=True)
    option_d = models.TextField(blank=True)
    correct_answer = models.CharField(max_length=20)

    # Verified justification for each answer choice.
    # These fields contain approved content; the voice layer only reads them.
    option_a_explanation = models.TextField(blank=True)
    option_b_explanation = models.TextField(blank=True)
    option_c_explanation = models.TextField(blank=True)
    option_d_explanation = models.TextField(blank=True)

    # Explanation / learning metadata
    source_explanation = models.TextField(blank=True)
    thestoreware_explanation = models.TextField(blank=True)
    exam_tip = models.TextField(blank=True)

    # Source traceability
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPE_CHOICES, default="manual", db_index=True)
    source_reference = models.CharField(max_length=500, blank=True)
    source_question_id = models.CharField(max_length=120, blank=True, db_index=True)

    # Publishing lifecycle
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["certification", "domain", "topic", "id"]
        indexes = [
            models.Index(fields=["category", "certification", "question_type"]),
            models.Index(fields=["certification", "domain", "difficulty"]),
        ]

    def __str__(self):
        return f"{self.certification or self.category} Q{self.pk or ''} - {self.question_text[:70]}"


class QuizExam(models.Model):
    TYPE_CHOICES = [
        ("quiz", "Quiz"),
        ("exam", "Exam Simulation"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("reviewed", "Reviewed"),
        ("published", "Published"),
        ("archived", "Archived"),
    ]

    category = models.CharField(max_length=100, db_index=True)
    certification = models.CharField(max_length=80, blank=True, db_index=True)
    title = models.CharField(max_length=250)
    slug = models.SlugField(max_length=180, unique=True)
    quiz_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default="quiz", db_index=True)

    # Assessment metadata:
    # QUIZ = flexible practice. Recommended time is normally question_count × seconds_per_question.
    # EXAM = certification simulation. official_question_count and official_duration_minutes
    #        define the intended international-exam simulation structure.
    seconds_per_question = models.PositiveIntegerField(default=80)
    official_question_count = models.PositiveIntegerField(null=True, blank=True)
    official_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    strict_timer = models.BooleanField(default=False)
    auto_submit_on_timeout = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    # Optional legacy/custom duration. For official exam simulations use
    # official_duration_minutes instead.
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    passing_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    show_answer_immediately = models.BooleanField(default=True)
    shuffle_questions = models.BooleanField(default=False)
    shuffle_choices = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    questions = models.ManyToManyField(
        QuestionBank,
        through="QuizExamQuestion",
        related_name="quiz_exams",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["certification", "quiz_type", "title"]

    def __str__(self):
        return f"{self.certification or self.category} - {self.title}"


class QuizExamQuestion(models.Model):
    quiz_exam = models.ForeignKey(QuizExam, on_delete=models.CASCADE, related_name="question_links")
    question = models.ForeignKey(QuestionBank, on_delete=models.CASCADE, related_name="quiz_links")
    sort_order = models.PositiveIntegerField(default=0)
    points = models.DecimalField(max_digits=6, decimal_places=2, default=1)

    class Meta:
        ordering = ["quiz_exam", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["quiz_exam", "question"],
                name="unique_question_per_quiz_exam",
            )
        ]

    def __str__(self):
        return f"{self.quiz_exam.title} - Q{self.sort_order or self.question_id}"



class QuestionAIExplanation(models.Model):
    """Reviewed, multilingual AI teaching content; one record per version/language."""

    LANGUAGE_CHOICES = [("en", "English"), ("ar", "Arabic"), ("fr", "French")]
    REVIEW_STATUS_CHOICES = [
        ("draft", "Draft"),
        ("needs_review", "Needs Review"),
        ("approved", "Approved"),
        ("published", "Published"),
        ("rejected", "Rejected"),
    ]
    MEDIA_STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("queued", "Queued"),
        ("ready", "Ready"),
        ("failed", "Failed"),
    ]

    question = models.ForeignKey(
        QuestionBank, on_delete=models.CASCADE, related_name="ai_explanations"
    )
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default="en")
    version = models.PositiveIntegerField(default=1)
    explanation_text = models.TextField(blank=True)
    short_summary = models.TextField(blank=True)
    key_learning_point = models.TextField(blank=True)
    exam_tip = models.TextField(blank=True)
    video_script = models.TextField(blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    audio_file = models.FileField(upload_to="learning/audio/", blank=True)
    video_file = models.FileField(upload_to="learning/video/", blank=True)
    video_url = models.URLField(max_length=1000, blank=True)
    voice_status = models.CharField(
        max_length=20, choices=MEDIA_STATUS_CHOICES, default="not_started"
    )
    video_status = models.CharField(
        max_length=20, choices=MEDIA_STATUS_CHOICES, default="not_started"
    )
    ai_provider = models.CharField(max_length=100, blank=True)
    model_used = models.CharField(max_length=120, blank=True)
    source_reference = models.CharField(max_length=500, blank=True)
    review_status = models.CharField(
        max_length=20, choices=REVIEW_STATUS_CHOICES, default="draft", db_index=True
    )
    accuracy_verified = models.BooleanField(default=False)
    reviewed_by = models.CharField(max_length=150, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["question_id", "language", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "language", "version"],
                name="unique_question_ai_explanation_language_version",
            )
        ]

    def __str__(self):
        return f"Q{self.question_id} - {self.language} - v{self.version}"
