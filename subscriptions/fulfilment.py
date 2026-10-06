"""Turn a completed Stripe Checkout session into an account and what it paid for.

Called by both the webhook and the success page, in either order and possibly
at the same time. One CheckoutFulfilment row per session makes that safe.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone

import stripe
from django.conf import settings
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin
from accounts.services import create_user_with_email_as_username
from core.models import Organization
from .models import (
    CheckoutFulfilment, OneTimeLoginToken, Plan, RoundPurchase, Subscription,
)

logger = logging.getLogger(__name__)

PLAN_TYPES = ('saas', 'enterprise', 'single')


@dataclass
class Account:
    """What a checkout resolved to."""
    organization: Organization
    user: User = None
    user_created: bool = False
    password: str = None      # generated password, only when user_created
    rejection: str = None     # a CheckoutFulfilment outcome, or None


def _period(sub):
    """(start, end) timestamps. Newer Stripe API versions keep them on the
    subscription item; fall back to the old top-level fields, then trial dates."""
    item = (sub.get('items') or {}).get('data') or [{}]
    item = item[0]
    start = item.get('current_period_start') or sub.get('current_period_start') or sub.get('trial_start') or sub.get('created')
    end = item.get('current_period_end') or sub.get('current_period_end') or sub.get('trial_end')
    return start, end


def _ts(value):
    return datetime.fromtimestamp(value, tz=dt_timezone.utc) if value else None


def _create_organization(user, name, email):
    organization = Organization.objects.create(name=name, email=email)
    UserProfile.objects.create(
        user=user, organization=organization, can_create_cycles_for_others=True,
    )
    assign_organization_admin(user)
    return organization


def resolve_checkout_account(session):
    """Find or create the organization this checkout pays for.

    Must run inside a transaction. See the account resolution table in the spec.
    """
    is_subscription = session['mode'] == 'subscription'

    # In-app: start_checkout sets client_reference_id and metadata.user_id. A
    # Payment Link visitor can set client_reference_id from the URL, but not
    # metadata, so the reference only counts when metadata names a member of
    # that same organization.
    organization_id = session.get('client_reference_id')
    user_id = (session.get('metadata') or {}).get('user_id')
    if organization_id and user_id:
        profile = (UserProfile.objects.filter(user_id=user_id).first()
                   if str(user_id).isdigit() else None)
        if profile is not None and str(profile.organization_id) == str(organization_id):
            organization = Organization.objects.select_for_update().get(pk=profile.organization_id)
            account = Account(organization=organization, user=profile.user)
            if is_subscription and Subscription.objects.filter(organization=organization).exists():
                account.rejection = 'rejected_duplicate_subscription'
            return account

    # Anonymous: all we have is the email typed into Stripe Checkout.
    details = session['customer_details']
    email = details['email']
    name = details.get('name') or email
    user = User.objects.filter(
        Q(email__iexact=email) | Q(username__iexact=email)
    ).order_by('date_joined').first()

    if user is None:
        user, password = create_user_with_email_as_username(
            email=email, password=None, is_staff=True, is_active=True,
        )
        return Account(organization=_create_organization(user, name, email),
                       user=user, user_created=True, password=password)

    profile = UserProfile.objects.filter(user=user).select_related('organization').first()
    if profile is None:
        # A superuser, or a user whose organization was deleted. Reuse the
        # user as-is: credentials and active flag are not touched.
        return Account(organization=_create_organization(user, name, user.email), user=user)

    if is_subscription:
        # An anonymous checkout must never change an existing organization's billing.
        return Account(organization=profile.organization, user=user,
                       rejection='rejected_existing_account')
    return Account(organization=profile.organization, user=user)


@transaction.atomic
def _fulfil(session, plan_type, stripe_subscription):
    """All writes for one session, or none. Returns (fulfilment, created, account)."""
    fulfilment, created = CheckoutFulfilment.objects.get_or_create(
        stripe_session_id=session['id'],
    )
    if not created:
        # Already processed. A concurrent caller waits on the unique index
        # until the first one commits, then lands here.
        return fulfilment, False, None

    # A subscription session fulfilled before CheckoutFulfilment existed has no
    # row, but its Subscription is on file. Replaying it must not look like a
    # second subscription and cancel the customer's live one.
    if stripe_subscription is not None:
        known = Subscription.objects.filter(
            stripe_subscription_id=session['subscription']).first()
        if known is not None:
            fulfilment.organization = known.organization
            fulfilment.save()
            return fulfilment, False, None

    account = resolve_checkout_account(session)

    if account.rejection:
        # Still in trial, so nothing was charged. Inside the transaction: if
        # the cancel fails, everything rolls back and the event is retried.
        if stripe_subscription['status'] != 'canceled':
            stripe.Subscription.cancel(session['subscription'])
    elif stripe_subscription is not None:
        start, end = _period(stripe_subscription)
        Subscription.objects.create(
            organization=account.organization,
            plan=Plan.objects.get(plan_type=plan_type),
            stripe_customer_id=session['customer'],
            stripe_subscription_id=session['subscription'],
            status=stripe_subscription.get('status', 'trialing'),
            current_period_start=_ts(start),
            current_period_end=_ts(end),
            trial_start=_ts(stripe_subscription.get('trial_start')),
            trial_end=_ts(stripe_subscription.get('trial_end')),
        )
    else:
        RoundPurchase.objects.create(organization=account.organization, fulfilment=fulfilment)

    if account.user_created:
        OneTimeLoginToken.objects.create(
            user=account.user, fulfilment=fulfilment,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    fulfilment.outcome = account.rejection or 'fulfilled'
    fulfilment.organization = account.organization
    fulfilment.user = account.user
    fulfilment.user_created = account.user_created
    fulfilment.save()
    return fulfilment, True, account


def _send_emails(fulfilment, account):
    """After commit, once. A failure is logged and never undoes the grant."""
    try:
        if account.user_created:
            from core.email import send_welcome_email
            send_welcome_email(account.user, account.organization, password=account.password)
        elif fulfilment.outcome == 'rejected_existing_account':
            from core.email import send_email
            send_email(
                subject='You already have a Blik360 account',
                message=(
                    f"You started a new subscription with {account.user.email}, but this "
                    "address already has a Blik360 account. We cancelled the new "
                    "subscription and nothing was charged.\n\n"
                    f"To choose a plan for your existing organization, sign in at "
                    f"{settings.SITE_URL} and open Settings.\n"
                ),
                recipient_list=[account.user.email],
            )
    except Exception:
        logger.exception("Checkout %s was fulfilled but its email failed",
                         fulfilment.stripe_session_id)


def fulfil_checkout(session):
    """Idempotently fulfil a completed Checkout session.

    Returns the CheckoutFulfilment, or None when the session is not ours or
    not paid. Raises on failure, with nothing written, so the caller can retry.
    """
    plan_type = (session.get('metadata') or {}).get('plan_type')
    if plan_type not in PLAN_TYPES:
        logger.warning("Ignoring checkout session %s: no known plan_type", session.get('id'))
        return None

    if session.get('status') != 'complete':
        logger.warning("Ignoring checkout session %s: not complete", session.get('id'))
        return None

    is_subscription = session['mode'] == 'subscription'
    if not is_subscription and session.get('payment_status') != 'paid':
        logger.warning("Ignoring unpaid checkout session %s", session.get('id'))
        return None

    stripe_subscription = None
    if is_subscription:
        stripe_subscription = stripe.Subscription.retrieve(session['subscription']).to_dict()

    try:
        fulfilment, created, account = _fulfil(session, plan_type, stripe_subscription)
    except IntegrityError:
        # Another checkout created the same user at the same moment. Its
        # transaction has committed by now, so a second pass finds that user.
        fulfilment, created, account = _fulfil(session, plan_type, stripe_subscription)

    if created:
        _send_emails(fulfilment, account)
    return fulfilment
