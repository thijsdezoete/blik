"""Subscription management services."""
import stripe
from django.conf import settings
from django.utils import timezone
from . import emails
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

    # Update local subscription. The webhook then sees no change, so the email goes out here.
    before = emails.snapshot(subscription)
    subscription.cancel_at_period_end = True
    subscription.save()
    emails.notify_change(before, subscription)

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

    # Update local subscription. The webhook then sees no change, so the email goes out here.
    before = emails.snapshot(subscription)
    subscription.cancel_at_period_end = False
    subscription.save()
    emails.notify_change(before, subscription)

    return subscription


def plan_change_items(subscription, plan):
    """The subscription items that move it to `plan`, for both the preview and the change."""
    from .utils import price_id_for
    stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
    item = stripe_sub['items']['data'][0]
    return [{'id': item['id'], 'price': price_id_for(plan.plan_type)}]


def preview_plan_change(subscription, plan):
    """Stripe's next invoice after moving to `plan`, with the price difference for this period."""
    return stripe.Invoice.create_preview(
        subscription=subscription.stripe_subscription_id,
        subscription_details={'items': plan_change_items(subscription, plan),
                              'proration_behavior': 'create_prorations'},
    )


def change_plan(subscription, plan):
    """Move the subscription to `plan` now; the price difference goes on the next invoice."""
    stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        items=plan_change_items(subscription, plan),
        proration_behavior='create_prorations',
    )

    # Update local subscription. The webhook then sees no change, so the email goes out here.
    before = emails.snapshot(subscription)
    subscription.plan = plan
    subscription.save()
    emails.notify_change(before, subscription)
    return subscription
