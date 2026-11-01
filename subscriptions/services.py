"""Subscription management services."""
import stripe
from django.conf import settings
from django.db import transaction
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

    # Cancel immediately in Stripe. A subscription Stripe no longer has is cancelled already.
    try:
        stripe.Subscription.delete(subscription.stripe_subscription_id)
    except stripe.InvalidRequestError as e:
        if e.code != 'resource_missing':
            raise

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
    """Move the subscription to `plan` now; the price difference goes on the next invoice.

    The row stays locked from before the change in Stripe until it is saved here, so the webhook for this
    change waits, then sees the new plan already and sends no second email. Only the plan is saved: the
    caller's copy may be older than what a webhook wrote.
    """
    with transaction.atomic():
        subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
        before = emails.snapshot(subscription)
        stripe.Subscription.modify(
            subscription.stripe_subscription_id,
            items=plan_change_items(subscription, plan),
            proration_behavior='create_prorations',
        )
        subscription.plan = plan
        subscription.save(update_fields=['plan', 'updated_at'])
    emails.notify_change(before, subscription)
    return subscription
