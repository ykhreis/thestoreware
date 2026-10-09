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