"""
API models for token authentication and webhooks.
"""
import secrets
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from core.models import TimeStampedModel, Organization
from core.managers import OrganizationManager

User = get_user_model()


class APIToken(TimeStampedModel):
    """
    API tokens for Bearer token authentication.

    Each token is scoped to an organization and has configurable permissions.
    Tokens can expire and have rate limiting.
    """

    # Public UUID for external references (API, URLs)
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Public identifier for API and URL usage (non-enumerable)"
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="api_tokens"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_api_tokens"
    )
    name = models.CharField(
        max_length=255, help_text="Descriptive name for the token (e.g., 'Slack Bot', 'Analytics Dashboard')"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True, editable=False)
    permissions = models.JSONField(
        default=dict,
        blank=True,
        help_text='Permissions as JSON: {"read:cycles": true, "write:cycles": true}',
    )
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="Token expiration date/time (null = never expires)"
    )
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    rate_limit = models.IntegerField(
        default=1000, help_text="Maximum requests per hour for this token"
    )

    objects = OrganizationManager()

    class Meta:
        db_table = "api_tokens"
        ordering = ["-created_at"]
        verbose_name = "API Token"
        verbose_name_plural = "API Tokens"

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def save(self, *args, **kwargs):
        """Auto-generate token if not set"""
        if not self.token:
            self.token = secrets.token_urlsafe(48)  # 64 chars after encoding
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        """Check if token has expired"""
        if not self.expires_at:
            return False
        from django.utils import timezone

        return self.expires_at < timezone.now()


class WebhookEndpoint(TimeStampedModel):
    """
    Webhook endpoints for event notifications.

    Endpoints receive HTTP POST requests when subscribed events occur.
    """

    # Public UUID for external references (API, URLs)
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Public identifier for API and URL usage (non-enumerable)"
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="webhook_endpoints"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_webhooks"
    )
    name = models.CharField(max_length=255, help_text="Descriptive name for this webhook")
    url = models.URLField(max_length=500, help_text="URL to receive webhook POST requests")
    events = models.JSONField(
        default=list,
        help_text='List of event types to subscribe to: ["cycle.created", "cycle.completed", ...]',
    )
    is_active = models.BooleanField(default=True)
    secret = models.CharField(
        max_length=64, editable=False, help_text="Secret for HMAC signature verification"
    )

    # Stats
    last_triggered_at = models.DateTimeField(null=True, blank=True, editable=False)
    success_count = models.IntegerField(default=0, editable=False)
    failure_count = models.IntegerField(default=0, editable=False)

    objects = OrganizationManager()

    class Meta:
        db_table = "webhook_endpoints"
        ordering = ["-created_at"]
        verbose_name = "Webhook Endpoint"
        verbose_name_plural = "Webhook Endpoints"

    def __str__(self):
        return f"{self.name} → {self.url}"

    def save(self, *args, **kwargs):
        """Auto-generate secret if not set"""
        if not self.secret:
            self.secret = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)


class WebhookDelivery(models.Model):
    """
    Log of webhook delivery attempts.

    Tracks each attempt to deliver a webhook, including retries.
    """

    id = models.AutoField(primary_key=True)  # Keep for internal use
    delivery_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
        help_text="Public UUID for this delivery (non-enumerable)"
    )
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    event_type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(help_text="Event data sent to webhook")

    # Delivery info
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True, help_text="Response body (truncated to 1000 chars)")
    error_message = models.TextField(blank=True)
    attempt_count = models.IntegerField(default=0)

    class Meta:
        db_table = "webhook_deliveries"
        ordering = ["-created_at"]
        verbose_name = "Webhook Delivery"
        verbose_name_plural = "Webhook Deliveries"
        indexes = [
            models.Index(fields=["endpoint", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]

    def __str__(self):
        status = "✓" if self.delivered_at else "✗"
        return f"{status} {self.event_type} → {self.endpoint.name} ({self.created_at})"

    @property
    def is_successful(self):
        """Check if delivery was successful"""
        return self.delivered_at is not None and 200 <= (self.status_code or 0) < 300
