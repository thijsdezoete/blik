"""Subscription management services."""
import stripe
from django.conf import settings
from django.utils import timezone
from .models import Subscription

stripe.api_key = settings.STRIPE_SECRET_KEY


def cancel_subscription(subscription):
    """
    Cancel a subscription at period end.

    Args:
        subscription: Subscription instance

    Returns:
        Updated subscription instance
    """
    if not subscription.stripe_subscription_id:
        raise ValueError("No Stripe subscription ID found")

    # Cancel at period end in Stripe
    stripe_sub = stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        cancel_at_period_end=True
    )

    # Update local subscription
    subscription.cancel_at_period_end = True
    subscription.save()

    return subscription


def cancel_subscription_immediately(subscription):
    """
    Cancel a subscription immediately.

    Args:
        subscription: Subscription instance

    Returns:
        Updated subscription instance
    """
    if not subscription.stripe_subscription_id:
        raise ValueError("No Stripe subscription ID found")

    # Cancel immediately in Stripe
    stripe.Subscription.delete(subscription.stripe_subscription_id)

    # Update local subscription
    subscription.status = 'canceled'
    subscription.canceled_at = timezone.now()
    subscription.save()

    return subscription


def reactivate_subscription(subscription):
    """
    Reactivate a subscription that was set to cancel at period end.

    Args:
        subscription: Subscription instance

    Returns:
        Updated subscription instance
    """
    if not subscription.cancel_at_period_end:
        return subscription

    # Reactivate in Stripe
    stripe_sub = stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        cancel_at_period_end=False
    )

    # Update local subscription
    subscription.cancel_at_period_end = False
    subscription.save()

    return subscription
