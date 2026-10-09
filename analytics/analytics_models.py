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

    # Network identifiers for security and future anonymous usage controls.
    first_ip_address = models.GenericIPAddressField(null=True, blank=True)
    last_ip_address = models.GenericIPAddressField(null=True, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True, db_index=True)

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

    ip_address = models.GenericIPAddressField(null=True, blank=True)

    country_code = models.CharField(
        max_length=2,
        blank=True
    )

    country_name = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)

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


class ServiceUsagePolicy(models.Model):
    """
    Configurable usage policy for a TheStoreWare service.

    Example:
        service_code = "ai_agent"
        anonymous_free_limit = 20
    """

    service_code = models.CharField(
        max_length=60,
        unique=True,
        db_index=True
    )

    service_name = models.CharField(max_length=120)

    anonymous_free_limit = models.PositiveIntegerField(default=20)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['service_name']

    def __str__(self):
        return self.service_name


class ServiceUsage(models.Model):
    """
    Audit record for one service request made by a visitor.

    This is deliberately transaction-based rather than storing only a
    counter on Visitor. It gives TheStoreWare a history of allowed/blocked
    requests and whether an external AI/API was used.
    """

    SOURCE_CHOICES = [
        ('local', 'Local Knowledge'),
        ('external_ai', 'External AI'),
        ('other', 'Other'),
        ('none', 'None / Not Executed'),
    ]

    visitor = models.ForeignKey(
        Visitor,
        on_delete=models.CASCADE,
        related_name='service_usage'
    )

    policy = models.ForeignKey(
        ServiceUsagePolicy,
        on_delete=models.PROTECT,
        related_name='usage_records'
    )

    session = models.ForeignKey(
        VisitSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_usage'
    )

    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)

    allowed = models.BooleanField(default=True, db_index=True)
    blocked_reason = models.CharField(max_length=255, blank=True)

    source_used = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default='none',
        db_index=True
    )

    external_api_used = models.BooleanField(default=False, db_index=True)

    # Optional cost tracking for external providers.
    estimated_external_cost = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True
    )

    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['visitor', 'policy', 'allowed']),
            models.Index(fields=['policy', 'requested_at']),
        ]

    def __str__(self):
        return (
            f"{self.policy.service_code} - "
            f"{self.visitor.visitor_id} - "
            f"{'Allowed' if self.allowed else 'Blocked'}"
        )

