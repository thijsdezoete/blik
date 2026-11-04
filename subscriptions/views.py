import stripe
import json
import logging

logger = logging.getLogger(__name__)
from django.conf import settings
from django.http import Http404, JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.shortcuts import redirect, render
from django.contrib import messages
from django.db import transaction
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit
from . import emails
from .models import OneTimeLoginToken, Plan, Subscription
from .billing import live_details, money
from .emails import DATA_RETENTION_DAYS
from .fulfilment import _period, _ts, fulfil_checkout
from .services import change_plan, preview_plan_change
from .utils import (
    CREDITS_PER_PACK, MAX_PACKS, SUPPORT_EMAIL, can_see_billing, cycle_credits,
    get_subscription_status, packs_for, price_id_for, purchased_credits, reviewees_over_limit,
    stripe_customer_id,
)
from core.url import get_absolute_url

stripe.api_key = settings.STRIPE_SECRET_KEY




def _base_url(request):
    """Public base URL of the main app (request host in local dev)."""
    if settings.DEBUG:
        scheme = 'https' if request.is_secure() else 'http'
        return f"{scheme}://{request.get_host()}"
    return settings.MAIN_APP_URL


def _create_session(plan_type, *, base_url, cancel_url, organization=None, user=None, quantity=1):
    """Create a Stripe Checkout session. Raises ValueError for an unknown plan.

    `organization` is passed only by the authenticated in-app view; it binds
    the purchase to that organization via client_reference_id, and reuses its
    Stripe customer so all its invoices and billing details stay in one place.

    Prices exclude VAT; Stripe Tax adds it from the billing address and VAT ID.

    No `payment_method_types`: Stripe API versions from 2026-09-30 reject it,
    and the methods offered come from the Stripe Dashboard settings. Some of
    those settle later (bank debits), which is why the webhook also handles
    checkout.session.async_payment_succeeded.
    """
    customer_id = stripe_customer_id(organization) if organization is not None else ''
    params = {
        'line_items': [{'price': price_id_for(plan_type), 'quantity': quantity}],
        'success_url': f'{base_url}/api/stripe/checkout-success/?session_id={{CHECKOUT_SESSION_ID}}',
        'cancel_url': cancel_url,
        'metadata': {'plan_type': plan_type},
        'automatic_tax': {'enabled': True},
        'tax_id_collection': {'enabled': True},
        'billing_address_collection': 'required',
    }
    if plan_type == 'single':
        params.update(mode='payment', invoice_creation={'enabled': True})
        # The buyer can change the number of packs on Stripe's page; fulfilment reads it from the line items.
        params['line_items'][0]['adjustable_quantity'] = {'enabled': True, 'minimum': 1, 'maximum': MAX_PACKS}
        if not customer_id:
            params['customer_creation'] = 'always'
    else:
        params['mode'] = 'subscription'
        # One trial per organization: a returning subscriber pays from day one.
        if organization is None or not Subscription.objects.filter(organization=organization).exists():
            params['subscription_data'] = {'trial_period_days': 14}
    if organization is not None:
        params['client_reference_id'] = str(organization.pk)
        params['metadata']['user_id'] = str(user.pk)
        if customer_id:
            params['customer'] = customer_id
            # Stripe needs these to save the address and VAT ID typed at checkout.
            params['customer_update'] = {'address': 'auto', 'name': 'auto'}
        else:
            params['customer_email'] = user.email
    return stripe.checkout.Session.create(**params)


@require_POST
@csrf_exempt  # Required: called from the landing page (different domain)
@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def create_checkout_session(request):
    """Public checkout for new customers. Never binds to an existing organization.

    CSRF-exempt because the landing page is on another origin. Protected by
    rate limiting and CORS; it only creates a Stripe session.
    """
    plan_type = None
    try:
        plan_type = json.loads(request.body).get('plan_type')
        base_url = _base_url(request)
        session = _create_session(
            plan_type, base_url=base_url,
            cancel_url=f'{base_url}/landing/signup/?canceled=true',
        )
    except ValueError:
        if plan_type in ('saas', 'enterprise', 'single'):
            logger.error('Checkout for plan %r failed: its Stripe price setting is empty', plan_type)
        return JsonResponse({'error': _('Unknown plan')}, status=400)
    except Exception:
        logger.exception('Error creating checkout session')
        return JsonResponse({'error': _('Could not create checkout session. Please try again.')}, status=400)
    return JsonResponse({'session_id': session.id, 'url': session.url})


@login_required
@require_POST
def start_checkout(request):
    """In-app purchase for an existing organization: another round, or a first subscription."""
    organization = getattr(request, 'organization', None)
    profile = getattr(request.user, 'profile', None)
    if (not organization or profile is None or profile.organization_id != organization.pk
            or not request.user.has_perm('accounts.can_manage_organization')):
        messages.error(request, _('Only organization administrators can manage billing.'))
        return redirect('settings')

    plan_type = request.POST.get('plan_type')
    if plan_type != 'single' and Subscription.objects.filter(
            organization=organization).exclude(status='canceled').exists():
        messages.error(request, _('This organization already has a subscription.'))
        return redirect('billing')

    quantity = 1
    if plan_type == 'single':
        try:
            quantity = packs_for(int(request.POST.get('reviews') or CREDITS_PER_PACK))
        except ValueError:
            quantity = 0
        if not 1 <= quantity <= MAX_PACKS:
            messages.error(request, _('Enter a number of reviews from 1 to %(max)s.')
                           % {'max': MAX_PACKS * CREDITS_PER_PACK})
            return redirect('billing')

    base_url = _base_url(request)
    try:
        session = _create_session(
            plan_type, base_url=base_url, cancel_url=f'{base_url}/dashboard/billing/',
            organization=organization, user=request.user, quantity=quantity,
        )
    except Exception:
        logger.exception('Error starting in-app checkout')
        messages.error(request, _('Could not start checkout. Please try again.'))
        return redirect('billing')
    return redirect(session.url)


@require_POST
@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events"""

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    try:
        # ponytail: .to_dict() because StripeObject stopped being a dict in stripe>=8
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        ).to_dict()
        logger.info("[STRIPE WEBHOOK] Received %s (%s)", event['type'], event.get('id'))
    except ValueError as e:
        logger.error(f"[STRIPE WEBHOOK] ✗ Invalid payload: {str(e)}")
        return HttpResponse(status=400)
    except stripe._error.SignatureVerificationError as e:
        logger.error(f"[STRIPE WEBHOOK] ✗ Signature verification failed: {str(e)}")
        return HttpResponse(status=400)

    # Handle the event
    try:
        # async_payment_succeeded is the "now it is paid" event for payment
        # methods that settle after the session completes. fulfil_checkout is
        # idempotent and ignores unpaid sessions, so both events go through it.
        if event['type'] in ('checkout.session.completed',
                             'checkout.session.async_payment_succeeded'):
            session = event['data']['object']
            fulfil_checkout(session)
            logger.info("[STRIPE WEBHOOK] ✓ Successfully processed %s", event['type'])

        elif event['type'] == 'customer.subscription.updated':
            subscription = event['data']['object']
            handle_subscription_updated(subscription)
            logger.info(f"[STRIPE WEBHOOK] ✓ Successfully processed customer.subscription.updated")

        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            handle_subscription_deleted(subscription)
            logger.info(f"[STRIPE WEBHOOK] ✓ Successfully processed customer.subscription.deleted")

        elif event['type'] == 'invoice.payment_failed':
            invoice = event['data']['object']
            handle_payment_failed(invoice)
            logger.info(f"[STRIPE WEBHOOK] ✓ Successfully processed invoice.payment_failed")
        else:
            logger.info("[STRIPE WEBHOOK] Ignored event type: %s", event['type'])

    except Exception:
        logger.exception("[STRIPE WEBHOOK] ✗ Error processing event %s", event['type'])
        # 500 so Stripe retries. Every handler is idempotent, and a failed
        # fulfilment leaves nothing behind.
        return HttpResponse(status=500)

    return HttpResponse(status=200)


def _plan_for(stripe_subscription):
    """The Plan of the subscription's price, or None for a price we do not sell."""
    item = ((stripe_subscription.get('items') or {}).get('data') or [{}])[0]
    price_id = (item.get('price') or {}).get('id')
    for plan_type in ('saas', 'enterprise'):
        try:
            if price_id and price_id == price_id_for(plan_type):
                return Plan.objects.filter(plan_type=plan_type).first()
        except ValueError:
            continue
    return None


def handle_subscription_updated(stripe_subscription):
    """Update subscription status and plan, and email the customer about the change."""
    try:
        # Locked: a plan change in the app holds this row until it has saved the new plan (see change_plan).
        with transaction.atomic():
            subscription = Subscription.objects.select_for_update().get(
                stripe_subscription_id=stripe_subscription['id']
            )
            before = emails.snapshot(subscription)
            start, end = _period(stripe_subscription)
            subscription.status = stripe_subscription['status']
            subscription.current_period_start = _ts(start)
            subscription.current_period_end = _ts(end)
            subscription.cancel_at_period_end = stripe_subscription.get('cancel_at_period_end', False)
            subscription.plan = _plan_for(stripe_subscription) or subscription.plan
            subscription.save()
        emails.notify_change(before, subscription)
    except Subscription.DoesNotExist:
        pass


def handle_subscription_deleted(stripe_subscription):
    """Mark subscription as canceled. Confirm it when the customer asked for it and was not told yet."""
    try:
        subscription = Subscription.objects.get(
            stripe_subscription_id=stripe_subscription['id']
        )
    except Subscription.DoesNotExist:
        return
    if subscription.canceled_at:
        return  # A retried event, or canceled here already

    # A scheduled cancellation was confirmed when it was scheduled. An ended subscription after
    # failed payments is Stripe's to report.
    reason = (stripe_subscription.get('cancellation_details') or {}).get('reason')
    confirm = reason == 'cancellation_requested' and not subscription.cancel_at_period_end

    subscription.status = 'canceled'
    subscription.canceled_at = timezone.now()
    subscription.save()

    if confirm:
        try:
            emails.send_cancellation_email(subscription)
        except Exception:
            logger.exception('Subscription %s ended but its email failed', subscription.pk)


def handle_payment_failed(invoice):
    """Handle failed payment"""
    stripe_customer_id = invoice['customer']
    try:
        subscription = Subscription.objects.get(stripe_customer_id=stripe_customer_id)
        before = emails.snapshot(subscription)
        subscription.status = 'past_due'
        subscription.save()
        # Stripe emails the failed payment itself. This only covers the end of a trial, which can
        # arrive here before customer.subscription.updated does.
        emails.notify_change(before, subscription)
    except Subscription.DoesNotExist:
        pass


def checkout_success(request):
    """Stripe's success redirect. Fulfil (or confirm) the purchase, then route the buyer."""
    session_id = request.GET.get('session_id')
    if not session_id:
        return redirect('login')

    try:
        session = stripe.checkout.Session.retrieve(session_id).to_dict()
    except Exception:
        logger.exception("[CHECKOUT SUCCESS] Could not retrieve session %s", session_id)
        return redirect('login')

    try:
        # Same idempotent call the webhook makes; whichever runs first does the work.
        fulfilment = fulfil_checkout(session)
    except Exception:
        logger.exception("[CHECKOUT SUCCESS] Fulfilment failed for %s", session_id)
        messages.info(request, _("Payment received. We're finishing your setup; "
                                 "you'll get an email shortly."))
        return redirect('login')

    if fulfilment is None:
        if session.get('status') == 'complete' and session.get('payment_status') == 'unpaid':
            messages.info(request, _("Your payment is being processed. You'll get an email "
                                     "as soon as it arrives and your account is ready."))
        return redirect('login')

    signed_in = request.user.is_authenticated

    if fulfilment.outcome == 'fulfilled' and fulfilment.user_created:
        # Only this checkout's own token. Never looked up by email.
        token = OneTimeLoginToken.objects.filter(
            fulfilment=fulfilment, used=False, expires_at__gt=timezone.now(),
        ).first()
        if token and (not signed_in or request.user == fulfilment.user):
            return redirect('subscriptions:auto_login', token=token.token)

    if fulfilment.outcome == 'fulfilled':
        messages.success(request, _('Payment received. Your purchase has been added to your account.'))
        return redirect('admin_dashboard' if signed_in else 'login')

    if fulfilment.outcome == 'rejected_existing_account':
        messages.error(request, _('This email address already has an account. The new subscription '
                                  'was cancelled and nothing was charged. Sign in and start the '
                                  'subscription from the Billing page.'))
    else:
        messages.error(request, _('This organization already has a subscription. The new one was '
                                  'cancelled and nothing was charged.'))
    return redirect('settings' if signed_in else 'login')


def auto_login(request, token):
    """Log in with a one-time token. Single use; never replaces another user's session."""
    login_token = OneTimeLoginToken.objects.filter(token=token).select_related('user').first()
    if login_token is None:
        return redirect('login')

    if request.user.is_authenticated and request.user != login_token.user:
        return redirect('admin_dashboard')

    # Conditional update: of two simultaneous requests, exactly one consumes it.
    consumed = OneTimeLoginToken.objects.filter(
        pk=login_token.pk, used=False, expires_at__gt=timezone.now(),
    ).update(used=True)
    if consumed != 1:
        return redirect('login')

    login(request, login_token.user, backend='django.contrib.auth.backends.ModelBackend')
    return redirect('setup_organization')


def _billing_organization(request):
    """The organization whose billing this user may manage, or 404."""
    organization = getattr(request, 'organization', None)
    if not can_see_billing(organization, request.user):
        raise Http404
    return organization


@login_required
def billing(request):
    """The billing page: status, usage, plan, credits, invoices and cancel."""
    organization = _billing_organization(request)
    subscription = Subscription.objects.select_related('plan').filter(organization=organization).first()
    can_change_plan = bool(subscription and subscription.is_active and not subscription.cancel_at_period_end)
    try:
        reviews = int(request.GET.get('reviews', CREDITS_PER_PACK))
    except ValueError:
        reviews = CREDITS_PER_PACK
    return render(request, 'admin_dashboard/billing.html', {
        'organization': organization,
        'subscription': subscription,
        'status': get_subscription_status(organization),
        'live': live_details(organization, subscription),
        'other_plans': (Plan.objects.filter(is_active=True, plan_type__in=('saas', 'enterprise'))
                        .exclude(pk=subscription.plan_id) if can_change_plan else []),
        'can_start_subscription': subscription is None or subscription.status == 'canceled',
        'round_credits': purchased_credits(organization),
        'cycle_credits': cycle_credits(organization),
        'reviews': max(1, min(reviews, MAX_PACKS * CREDITS_PER_PACK)),
        'credits_per_pack': CREDITS_PER_PACK,
        'max_reviews': MAX_PACKS * CREDITS_PER_PACK,
        'retention_days': DATA_RETENTION_DAYS,
        'support_email': SUPPORT_EMAIL,
    })


@login_required
def change_plan_view(request, plan_type):
    """Confirm a plan change with Stripe's price preview, then make it."""
    organization = _billing_organization(request)
    subscription = Subscription.objects.select_related('plan').filter(organization=organization).first()
    if not subscription or not subscription.is_active or subscription.cancel_at_period_end:
        return redirect('billing')
    plan = Plan.objects.filter(plan_type=plan_type, is_active=True).exclude(pk=subscription.plan_id).first()
    if plan is None or plan_type not in ('saas', 'enterprise'):
        raise Http404

    over_limit = reviewees_over_limit(organization, plan)
    try:
        if request.method == 'POST' and not over_limit:
            change_plan(subscription, plan)
            messages.success(request, _('Your plan is now %(plan)s.') % {'plan': plan.name})
            return redirect('billing')
        preview = None if over_limit else preview_plan_change(subscription, plan)
    except stripe.StripeError:
        logger.exception('Plan change for organization %s failed', organization.pk)
        messages.error(request, _('Could not change the plan. Please try again, or contact us.'))
        return redirect('billing')

    return render(request, 'admin_dashboard/billing_change_plan.html', {
        'subscription': subscription,
        'plan': plan,
        'over_limit': over_limit,
        'next_invoice': preview and {
            'total': money(preview['amount_due'], preview['currency']),
            'date': _ts(preview['next_payment_attempt'] or preview['period_end']),
        },
    })


@login_required
def billing_portal(request):
    """Stripe's portal for the card, billing details (VAT ID) and invoices."""
    organization = _billing_organization(request)
    customer_id = stripe_customer_id(organization)
    if not customer_id:
        messages.error(request, _('There are no billing details yet. They are made with your first purchase.'))
        return redirect('billing')
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id, return_url=get_absolute_url('billing'),
        )
    except stripe.StripeError:
        logger.exception("Error creating billing portal session")
        messages.error(request, _('Could not open the billing portal. Please try again.'))
        return redirect('billing')
    return redirect(session.url)
