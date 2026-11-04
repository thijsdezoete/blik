from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext, gettext_lazy as _
from core.models import TimeStampedModel, Organization
import secrets


class Plan(models.Model):
    """Subscription plan tiers"""
    PLAN_TYPES = [
        ('saas', _('EU SaaS')),
        ('enterprise', _('Enterprise')),
    ]

    name = models.CharField(_('name'), max_length=100)
    plan_type = models.CharField(_('plan type'), max_length=20, choices=PLAN_TYPES, unique=True)
    price_monthly = models.DecimalField(_('monthly price'), max_digits=10, decimal_places=2)
    max_employees = models.IntegerField(_('maximum employees'), help_text=_('Maximum total: reviewees + team members combined'))
    stripe_price_id = models.CharField(_('Stripe price ID'), max_length=255, blank=True)
    features = models.JSONField(_('features'), default=dict)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        verbose_name = _('plan')
        verbose_name_plural = _('plans')
        db_table = 'plans'

    def __str__(self):
        return gettext('%(name)s (€%(price)s/mo)') % {'name': self.name, 'price': self.price_monthly}


class Subscription(TimeStampedModel):
    """Customer subscription tracking"""
    STATUS_CHOICES = [
        ('trialing', _('Trial')),
        ('active', _('Active')),
        ('past_due', _('Past Due')),
        ('canceled', _('Canceled')),
        ('unpaid', _('Unpaid')),
    ]

    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name='subscription',
        verbose_name=_('organization')
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='subscriptions',
        verbose_name=_('plan')
    )

    # Stripe identifiers
    stripe_customer_id = models.CharField(_('Stripe customer ID'), max_length=255, unique=True, db_index=True)
    stripe_subscription_id = models.CharField(_('Stripe subscription ID'), max_length=255, unique=True, db_index=True)

    # Subscription state
    status = models.CharField(_('status'), max_length=20, choices=STATUS_CHOICES, default='active')
    current_period_start = models.DateTimeField(_('current period start'))
    current_period_end = models.DateTimeField(_('current period end'))
    cancel_at_period_end = models.BooleanField(_('cancel at period end'), default=False)
    canceled_at = models.DateTimeField(_('canceled at'), null=True, blank=True)

    # Trial period
    trial_start = models.DateTimeField(_('trial start'), null=True, blank=True)
    trial_end = models.DateTimeField(_('trial end'), null=True, blank=True)

    # When the trial-ending reminders went out, so the daily run sends each one once
    trial_reminder_3_days_sent_at = models.DateTimeField(_('3-day trial reminder sent at'), null=True, blank=True)
    trial_reminder_1_day_sent_at = models.DateTimeField(_('1-day trial reminder sent at'), null=True, blank=True)

    class Meta:
        verbose_name = _('subscription')
        verbose_name_plural = _('subscriptions')
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


class CheckoutFulfilment(TimeStampedModel):
    """One row per processed Stripe Checkout session.

    It is the idempotency key, the lock between webhook and success page,
    and the owner of the auto-login token.
    """
    OUTCOME_CHOICES = [
        ('fulfilled', _('Fulfilled')),
        ('rejected_existing_account', _('Rejected: email already has an account')),
        ('rejected_duplicate_subscription', _('Rejected: organization already subscribed')),
    ]

    stripe_session_id = models.CharField(_('Stripe session ID'), max_length=255, unique=True)
    # Final value is set before the fulfilment transaction commits.
    outcome = models.CharField(_('outcome'), max_length=40, choices=OUTCOME_CHOICES, default='fulfilled')
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='checkout_fulfilments',
        verbose_name=_('organization'),
    )
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='checkout_fulfilments',
        verbose_name=_('user'),
    )
    user_created = models.BooleanField(_('user created'), default=False)

    class Meta:
        verbose_name = _('checkout fulfilment')
        verbose_name_plural = _('checkout fulfilments')
        db_table = 'checkout_fulfilments'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.stripe_session_id} ({self.outcome})"


class RoundPurchase(TimeStampedModel):
    """A one-time purchase of review-cycle credits."""
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='round_purchases',
        verbose_name=_('organization'),
    )
    # Null only for credits granted by hand in admin.
    fulfilment = models.OneToOneField(
        CheckoutFulfilment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='round_purchase',
        verbose_name=_('checkout fulfilment'),
    )
    cycles_remaining = models.PositiveIntegerField(_('review cycles remaining'), default=10)

    class Meta:
        verbose_name = _('round purchase')
        verbose_name_plural = _('round purchases')
        db_table = 'round_purchases'
        ordering = ['created_at']

    def __str__(self):
        return gettext('%(organization)s: %(count)s credit(s) left') % {'organization': self.organization.name, 'count': self.cycles_remaining}


class OneTimeLoginToken(TimeStampedModel):
    """One-time use login token for auto-login after Stripe checkout"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_tokens', verbose_name=_('user'))
    token = models.CharField(_('token'), max_length=64, unique=True, db_index=True)
    used = models.BooleanField(_('used'), default=False)
    expires_at = models.DateTimeField(_('expires at'))
    # Set when the token was issued by a checkout; that checkout is the only
    # thing allowed to redeem it.
    fulfilment = models.OneToOneField(
        'CheckoutFulfilment', null=True, blank=True, on_delete=models.CASCADE,
        related_name='login_token',
        verbose_name=_('checkout fulfilment'),
    )

    class Meta:
        verbose_name = _('one-time login token')
        verbose_name_plural = _('one-time login tokens')
        db_table = 'one_time_login_tokens'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def __str__(self):
        return gettext('Login token for %(email)s') % {'email': self.user.email}
