from django.db import models
from django.contrib.auth.models import User
from core.models import TimeStampedModel, Organization
import secrets


class Plan(models.Model):
    """Subscription plan tiers"""
    PLAN_TYPES = [
        ('saas', 'EU SaaS'),
        ('enterprise', 'Enterprise'),
    ]

    name = models.CharField(max_length=100)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPES, unique=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2)
    max_employees = models.IntegerField()
    stripe_price_id = models.CharField(max_length=255, blank=True)
    features = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'plans'

    def __str__(self):
        return f"{self.name} (€{self.price_monthly}/mo)"


class Subscription(TimeStampedModel):
    """Customer subscription tracking"""
    STATUS_CHOICES = [
        ('trialing', 'Trial'),
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
        ('unpaid', 'Unpaid'),
    ]

    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='subscriptions'
    )

    # Stripe identifiers
    stripe_customer_id = models.CharField(max_length=255, unique=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=255, unique=True, db_index=True)

    # Subscription state
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)

    # Trial period
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'subscriptions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.organization.name} - {self.plan.name} ({self.status})"

    @property
    def is_active(self):
        return self.status in ['active', 'trialing']

    @property
    def is_past_due(self):
        return self.status == 'past_due'


class OneTimeLoginToken(TimeStampedModel):
    """One-time use login token for auto-login after Stripe checkout"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_tokens')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'one_time_login_tokens'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Login token for {self.user.email}"
