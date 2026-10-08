from django.db import models


class Visitor(models.Model):
    """
    Anonymous website visitor.

    We deliberately avoid storing personal information such as
    names, emails, or raw IP addresses.
    """

    visitor_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True
    )

    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    first_language = models.CharField(
        max_length=20,
        blank=True
    )

    first_referrer = models.TextField(
        blank=True
    )

    visit_count = models.PositiveIntegerField(default=1)

    is_bot = models.BooleanField(default=False)

    class Meta:
        ordering = ['-last_seen']

    def __str__(self):
        return self.visitor_id


class VisitSession(models.Model):
    """
    One browsing session belonging to an anonymous visitor.
    """

    visitor = models.ForeignKey(
        Visitor,
        on_delete=models.CASCADE,
        related_name='sessions'
    )

    session_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True
    )

    started_at = models.DateTimeField(auto_now_add=True)

    last_activity = models.DateTimeField(auto_now=True)

    ended_at = models.DateTimeField(
        null=True,
        blank=True
    )

    entry_page = models.TextField(blank=True)

    exit_page = models.TextField(blank=True)

    referrer = models.TextField(blank=True)

    language = models.CharField(
        max_length=20,
        blank=True
    )

    device_type = models.CharField(
        max_length=30,
        blank=True
    )

    browser = models.CharField(
        max_length=60,
        blank=True
    )

    operating_system = models.CharField(
        max_length=60,
        blank=True
    )

    country_code = models.CharField(
        max_length=2,
        blank=True
    )

    page_view_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return self.session_id


class PageView(models.Model):
    """
    Individual page request recorded during a visitor session.
    """

    session = models.ForeignKey(
        VisitSession,
        on_delete=models.CASCADE,
        related_name='page_views'
    )

    path = models.TextField()

    page_title = models.CharField(
        max_length=255,
        blank=True
    )

    viewed_at = models.DateTimeField(auto_now_add=True)

    referrer = models.TextField(blank=True)

    language = models.CharField(
        max_length=20,
        blank=True
    )

    duration_seconds = models.PositiveIntegerField(
        null=True,
        blank=True
    )

    class Meta:
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['viewed_at']),
        ]

    def __str__(self):
        return self.path