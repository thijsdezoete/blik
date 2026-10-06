"""Shared builders for subscriptions tests."""
from django.utils import timezone

from .models import Plan, RoundPurchase, Subscription


def subscribe(organization, status='active', max_employees=50):
    plan, _ = Plan.objects.get_or_create(
        plan_type='saas',
        defaults={'name': 'EU SaaS', 'price_monthly': 49, 'max_employees': max_employees},
    )
    now = timezone.now()
    return Subscription.objects.create(
        organization=organization, plan=plan,
        stripe_customer_id=f'cus_{organization.pk}',
        stripe_subscription_id=f'sub_{organization.pk}',
        status=status, current_period_start=now, current_period_end=now,
    )


def grant(organization, credits=10):
    return RoundPurchase.objects.create(organization=organization, cycles_remaining=credits)


def checkout_session(**overrides):
    """A paid single-round Checkout session as the webhook delivers it."""
    session = {
        'id': 'cs_1', 'mode': 'payment', 'payment_status': 'paid',
        'customer': 'cus_1', 'subscription': None, 'client_reference_id': None,
        'customer_details': {'email': 'buyer@example.com', 'name': 'Buyer Inc'},
        'metadata': {'plan_type': 'single'},
    }
    session.update(overrides)
    return session


def subscription_session(**overrides):
    values = {
        'mode': 'subscription', 'subscription': 'sub_1',
        'payment_status': 'no_payment_required',
        'metadata': {'plan_type': 'saas'},
    }
    values.update(overrides)
    return checkout_session(**values)


STRIPE_SUBSCRIPTION = {
    'id': 'sub_1', 'status': 'trialing', 'created': 1_700_000_000,
    'trial_start': 1_700_000_000, 'trial_end': 1_701_209_600,
    'cancel_at_period_end': False,
    'items': {'data': [{'current_period_start': 1_700_000_000,
                        'current_period_end': 1_701_209_600}]},
}
