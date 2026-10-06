from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from accounts.models import Reviewee, UserProfile
from .models import RoundPurchase, Subscription


class NoCycleCredits(Exception):
    """Raised when an organization in credits mode cannot pay for new cycles."""

    def __init__(self, needed, available):
        self.needed = needed
        self.available = available
        super().__init__(
            f"This needs {needed} review-cycle credit(s) and you have {available}. "
            "Buy another round or start a subscription under Settings."
        )


def entitlement(organization):
    """Which rules apply to this organization. The only place that decides.

    'subscription'  active or trialing subscription
    'credits'       no active subscription, has bought at least one round
    'lapsed'        a subscription row that is not active, never bought a round
    'self_hosted'   neither
    """
    subscription = Subscription.objects.filter(organization=organization).first()
    if subscription and subscription.is_active:
        return 'subscription'
    if RoundPurchase.objects.filter(organization=organization).exists():
        return 'credits'
    return 'lapsed' if subscription else 'self_hosted'


def is_hosted_customer(organization):
    """True for anyone who ever paid us, whatever their status or balance."""
    return (
        Subscription.objects.filter(organization=organization).exists()
        or RoundPurchase.objects.filter(organization=organization).exists()
    )


def purchased_credits(organization):
    """Unspent credits across all purchases; None if no round was ever bought."""
    purchases = RoundPurchase.objects.filter(organization=organization)
    if not purchases.exists():
        return None
    return purchases.aggregate(total=Sum('cycles_remaining'))['total']


def cycle_credits(organization):
    """Spendable balance in credits mode; None when credits do not apply."""
    if entitlement(organization) != 'credits':
        return None
    return purchased_credits(organization)


def consume_cycle_credits(organization, n=1):
    """Spend n credits, oldest purchase first, or raise NoCycleCredits and spend none."""
    with transaction.atomic():
        if entitlement(organization) != 'credits':
            return
        purchases = list(
            RoundPurchase.objects.select_for_update()
            .filter(organization=organization, cycles_remaining__gt=0)
            .order_by('created_at', 'pk')
        )
        available = sum(p.cycles_remaining for p in purchases)
        if available < n:
            raise NoCycleCredits(needed=n, available=available)
        for purchase in purchases:
            take = min(purchase.cycles_remaining, n)
            purchase.cycles_remaining -= take
            purchase.save(update_fields=['cycles_remaining'])
            n -= take
            if n == 0:
                break


def check_user_limit(request):
    """Team members are unlimited on every plan."""
    return True, None


def check_employee_limit(organization):
    """(allowed, message) for adding one reviewee."""
    if not organization:
        return True, None  # single-tenant mode
    mode = entitlement(organization)
    if mode == 'lapsed':
        return False, "Your subscription is not active. Please update your payment information."
    if mode == 'subscription':
        max_employees = organization.subscription.plan.max_employees
        active = Reviewee.objects.filter(organization=organization, is_active=True).count()
        if active >= max_employees:
            return False, (
                f"You've reached your plan limit of {max_employees} reviewees. "
                "Please upgrade your plan."
            )
    return True, None


def get_subscription_status(organization):
    """Plan and usage information for dashboard templates."""
    mode = entitlement(organization)
    status = {
        'mode': mode,
        'cycle_credits': cycle_credits(organization),
        # In credits mode the plan and its reviewee cap do not apply, so the
        # plan widgets stay hidden even if an old subscription row exists.
        'has_subscription': mode in ('subscription', 'lapsed'),
        'is_active': mode != 'lapsed',
        'is_past_due': False,
    }
    if not status['has_subscription']:
        return status

    subscription = Subscription.objects.select_related('plan').get(organization=organization)
    active_reviewees = Reviewee.objects.filter(organization=organization, is_active=True).count()
    status.update({
        'is_past_due': subscription.is_past_due,
        'plan_name': subscription.plan.name,
        'max_employees': subscription.plan.max_employees,
        'current_reviewees': active_reviewees,
        'reviewees_remaining': subscription.plan.max_employees - active_reviewees,
        'current_users': UserProfile.objects.filter(organization=organization).count(),
        'current_period_end': subscription.current_period_end,
    })
    return status


def billing_context(organization, user):
    """Template context for the in-app purchase UI."""
    hosted = is_hosted_customer(organization)
    return {
        'is_hosted': hosted,
        'round_credits': purchased_credits(organization),
        'cycle_credits': cycle_credits(organization),
        'can_start_subscription': hosted and not Subscription.objects.filter(
            organization=organization).exists(),
        'is_org_admin': user.has_perm('accounts.can_manage_organization'),
    }


def price_id_for(plan_type):
    """The Stripe price for a plan type. The client never chooses the price."""
    price_id = {
        'saas': settings.STRIPE_PRICE_ID_SAAS,
        'enterprise': settings.STRIPE_PRICE_ID_ENTERPRISE,
        'single': settings.STRIPE_PRICE_ID_SINGLE,
    }.get(plan_type)
    if not price_id:
        raise ValueError(f"No Stripe price configured for plan type {plan_type!r}")
    return price_id
