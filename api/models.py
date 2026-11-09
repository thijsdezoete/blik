"""
API models for token authentication and webhooks.
"""
import hashlib
import secrets
import uuid
from django.db import models
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from core.models import TimeStampedModel, Organization
from core.managers import OrganizationManager

User = get_user_model()


MAX_RATE_LIMIT = 10000


def hash_token(raw):
    """Tokens are stored as their SHA-256: a database leak gives no working tokens."""
    return hashlib.sha256(raw.encode()).hexdigest()


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
        help_text=_("Public identifier for API and URL usage (non-enumerable)"),
        verbose_name=_("UUID")
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="api_tokens", verbose_name=_("organization")
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_api_tokens", verbose_name=_("created by")
    )
    name = models.CharField(
        max_length=255, help_text="Descriptive name for the token (e.g., 'Slack Bot', 'Analytics Dashboard')", verbose_name=_("name")
    )
    # The SHA-256 of the token; the token itself is shown once, on creation
    token = models.CharField(_("token"), max_length=64, unique=True, db_index=True, editable=False)
    prefix = models.CharField(_("prefix"), max_length=8, blank=True, editable=False,
                              help_text=_("First characters of the token, to recognize it"))
    permissions = models.JSONField(
        default=dict,
        blank=True,
        help_text=format_lazy(_("Permissions as JSON: {example}"), example='{"read:cycles": true, "write:cycles": true}'),
        verbose_name=_("permissions"),
    )
    is_active = models.BooleanField(_("active"), default=True)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="Token expiration date/time (null = never expires)", verbose_name=_("expires at")
    )
    last_used_at = models.DateTimeField(_("last used at"), null=True, blank=True, editable=False)
    rate_limit = models.IntegerField(
        default=1000, help_text="Maximum requests per hour for this token", verbose_name=_("rate limit")
    )

    objects = OrganizationManager()

    class Meta:
        db_table = "api_tokens"
        ordering = ["-created_at"]
        verbose_name = _("API Token")
        verbose_name_plural = _("API Tokens")

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def save(self, *args, **kwargs):
        """Generate the token on creation; only its hash is stored, the raw value lives on raw_token."""
        if not self.token:
            self.raw_token = secrets.token_urlsafe(48)  # 64 chars after encoding
            self.prefix = self.raw_token[:8]
            self.token = hash_token(self.raw_token)
        self.rate_limit = max(1, min(int(self.rate_limit), MAX_RATE_LIMIT))
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
        help_text=_("Public identifier for API and URL usage (non-enumerable)"),
        verbose_name=_("UUID")
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="webhook_endpoints", verbose_name=_("organization")
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_webhooks", verbose_name=_("created by")
    )
    name = models.CharField(_("name"), max_length=255, help_text="Descriptive name for this webhook")
    url = models.URLField(_("URL"), max_length=500, help_text="URL to receive webhook POST requests")
    events = models.JSONField(
        default=list,
        help_text=format_lazy(_("List of event types to subscribe to: {example}"), example='["cycle.created", "cycle.completed", ...]'),
        verbose_name=_("events"),
    )
    is_active = models.BooleanField(_("active"), default=True)
    secret = models.CharField(
        max_length=64, editable=False, help_text="Secret for HMAC signature verification", verbose_name=_("secret")
    )

    # Stats
    last_triggered_at = models.DateTimeField(_("last triggered at"), null=True, blank=True, editable=False)
    success_count = models.IntegerField(_("success count"), default=0, editable=False)
    failure_count = models.IntegerField(_("failure count"), default=0, editable=False)

    objects = OrganizationManager()

    class Meta:
        db_table = "webhook_endpoints"
        ordering = ["-created_at"]
        verbose_name = _("Webhook Endpoint")
        verbose_name_plural = _("Webhook Endpoints")

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

    id = models.AutoField(_("ID"), primary_key=True)  # Keep for internal use
    delivery_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
        help_text=_("Public UUID for this delivery (non-enumerable)"),
        verbose_name=_("delivery ID")
    )
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries", verbose_name=_("endpoint")
    )
    event_type = models.CharField(_("event type"), max_length=100, db_index=True)
    payload = models.JSONField(_("payload"), help_text="Event data sent to webhook")

    # Delivery info
    created_at = models.DateTimeField(_("created at"), auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(_("delivered at"), null=True, blank=True)
    status_code = models.IntegerField(_("status code"), null=True, blank=True)
    response_body = models.TextField(_("response body"), blank=True, help_text="Response body (truncated to 1000 chars)")
    error_message = models.TextField(_("error message"), blank=True)
    attempt_count = models.IntegerField(_("attempt count"), default=0)

    class Meta:
        db_table = "webhook_deliveries"
        ordering = ["-created_at"]
        verbose_name = _("Webhook Delivery")
        verbose_name_plural = _("Webhook Deliveries")
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
