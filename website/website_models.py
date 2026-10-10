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
