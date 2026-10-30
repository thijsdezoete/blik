"""
Context processors for making settings available in templates.
"""
from django.conf import settings


def site_settings(request):
    """Public base URL for links shown in the UI (never request.get_host(),
    which is the internal proxy hostname behind nginx/docker)."""
    return {'SITE_URL': settings.SITE_URL}


def stripe_settings(request):
    """
    Make Stripe configuration available in templates.
    Used to conditionally show/hide features based on Stripe setup.
    """
    return {
        'STRIPE_PRICE_ID_SAAS': settings.STRIPE_PRICE_ID_SAAS,
        'STRIPE_PRICE_ID_ENTERPRISE': settings.STRIPE_PRICE_ID_ENTERPRISE,
        'HAS_STRIPE_CONFIGURED': bool(
            settings.STRIPE_PRICE_ID_SAAS
            or settings.STRIPE_PRICE_ID_ENTERPRISE
            or settings.STRIPE_PRICE_ID_SINGLE
        ),
    }


def billing(request):
    """The billing nav link, and a banner while the subscription needs the admin's action."""
    from subscriptions.models import Subscription
    from subscriptions.utils import can_see_billing, entitlement

    user = getattr(request, 'user', None)
    organization = getattr(request, 'organization', None)
    # ponytail: a few small queries on every dashboard page; cache per request if it ever shows up in profiles
    if not (user and user.is_authenticated and can_see_billing(organization, user)):
        return {}
    unpaid = Subscription.objects.filter(organization=organization, status__in=('past_due', 'unpaid')).exists()
    return {
        'show_billing': True,
        # A failed payment also counts as lapsed, so check it first: Stripe is still retrying.
        'billing_problem': 'unpaid' if unpaid else 'lapsed' if entitlement(organization) == 'lapsed' else None,
    }
