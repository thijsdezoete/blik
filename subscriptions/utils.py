from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _, gettext_lazy

from accounts.models import Reviewee, UserProfile
from .models import RoundPurchase, Subscription


class NoCycleCredits(Exception):
    """Raised when an organization in credits mode cannot pay for new cycles."""

    def __init__(self, needed, available):
        self.needed = needed
        self.available = available
        super().__init__(
            _('This needs %(needed)s review-cycle credit(s) and you have %(available)s. '
              'Buy more on the Billing page, or start a subscription there.')
            % {'needed': needed, 'available': available}
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


def billing_enabled():
    """True when this instance runs the hosted SaaS: it can charge in Stripe and receives Stripe's webhooks.

    ponytail: checks the configuration, not the live Stripe account; a revoked key still passes.
    """
    return bool(
        settings.STRIPE_SECRET_KEY.startswith(('sk_', 'rk_'))
        and settings.STRIPE_WEBHOOK_SECRET
        and (settings.STRIPE_PRICE_ID_SAAS or settings.STRIPE_PRICE_ID_ENTERPRISE)
    )


def is_hosted_customer(organization):
    """True for anyone who ever paid us, whatever their status or balance."""
    return (
        Subscription.objects.filter(organization=organization).exists()
        or RoundPurchase.objects.filter(organization=organization).exists()
    )


def can_see_billing(organization, user):
    """The billing page, its nav link and the banner: hosted customers' admins only."""
    return bool(
        organization
        and billing_enabled()
        and user.has_perm('accounts.can_manage_organization')
        and is_hosted_customer(organization)
    )


SUPPORT_EMAIL = 'thijs@mail.blik360.com'


def stripe_customer_id(organization):
    """The organization's Stripe customer, or ''. Subscribers from before the billing page have it only on
    their subscription until backfill_stripe_customers runs."""
    return organization.stripe_customer_id or (
        Subscription.objects.filter(organization=organization)
        .values_list('stripe_customer_id', flat=True).first() or '')


# One round purchase (€19) grants this many review-cycle credits.
CREDITS_PER_PACK = 10
# ponytail: a sanity cap on one checkout, not a business rule; raise it when someone hits it
MAX_PACKS = 100


def packs_for(reviews):
    """Packs to buy for this many reviews: always at least one."""
    return max(1, -(-reviews // CREDITS_PER_PACK))  # integer ceil: a float overflows on huge input


def reviewees_over_limit(organization, plan):
    """How many active reviewees must be deactivated before moving to this plan; 0 when they fit."""
    active = Reviewee.objects.filter(organization=organization, is_active=True).count()
    return max(0, active - plan.max_employees)


# Stripe decline codes we can explain. Others show Stripe's own message.
PAYMENT_ERRORS = {
    'insufficient_funds': gettext_lazy('The card was declined: not enough funds.'),
    'expired_card': gettext_lazy('The card has expired.'),
    'card_declined': gettext_lazy('The card was declined by the bank.'),
    'generic_decline': gettext_lazy('The card was declined by the bank.'),
    'do_not_honor': gettext_lazy('The card was declined by the bank.'),
    'lost_card': gettext_lazy('The card was reported lost.'),
    'stolen_card': gettext_lazy('The card was reported stolen.'),
    'incorrect_cvc': gettext_lazy('The security code (CVC) is wrong.'),
    'authentication_required': gettext_lazy('The bank asks you to confirm the payment.'),
}


def payment_error_text(error):
    """Clear text for a PaymentIntent's last_payment_error; None when there is no error."""
    if not error:
        return None
    for code in (error.get('decline_code'), error.get('code')):
        if code in PAYMENT_ERRORS:
            return str(PAYMENT_ERRORS[code])
    return error.get('message') or str(PAYMENT_ERRORS['card_declined'])


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
        return False, _('Your subscription is not active. Please update your payment information.')
    if mode == 'subscription':
        max_employees = organization.subscription.plan.max_employees
        active = Reviewee.objects.filter(organization=organization, is_active=True).count()
        if active >= max_employees:
            return False, (
                _("You've reached your plan limit of %(max_employees)s reviewees. "
                  "Please upgrade your plan.")
                % {'max_employees': max_employees}
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
        'can_buy_round': hosted and entitlement(organization) != 'subscription',
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
