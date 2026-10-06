import stripe
import json
import logging

logger = logging.getLogger(__name__)
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django_ratelimit.decorators import ratelimit
from .models import Subscription, OneTimeLoginToken
from .fulfilment import _period, _ts, fulfil_checkout
from .utils import price_id_for

stripe.api_key = settings.STRIPE_SECRET_KEY




def _base_url(request):
    """Public base URL of the main app (request host in local dev)."""
    if settings.DEBUG:
        scheme = 'https' if request.is_secure() else 'http'
        return f"{scheme}://{request.get_host()}"
    return settings.MAIN_APP_URL


def _create_session(plan_type, *, base_url, cancel_url, organization=None, user=None):
    """Create a Stripe Checkout session. Raises ValueError for an unknown plan.

    `organization` is passed only by the authenticated in-app view; it binds
    the purchase to that organization via client_reference_id.
    """
    params = {
        'payment_method_types': ['card'],
        'line_items': [{'price': price_id_for(plan_type), 'quantity': 1}],
        'success_url': f'{base_url}/api/stripe/checkout-success/?session_id={{CHECKOUT_SESSION_ID}}',
        'cancel_url': cancel_url,
        'metadata': {'plan_type': plan_type},
    }
    if plan_type == 'single':
        params.update(mode='payment', customer_creation='always',
                      invoice_creation={'enabled': True})
    else:
        params.update(mode='subscription', subscription_data={'trial_period_days': 14})
    if organization is not None:
        params['client_reference_id'] = str(organization.pk)
        params['customer_email'] = user.email
        params['metadata']['user_id'] = str(user.pk)
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
        return JsonResponse({'error': 'Unknown plan'}, status=400)
    except Exception:
        logger.exception('Error creating checkout session')
        return JsonResponse({'error': 'Could not create checkout session. Please try again.'}, status=400)
    return JsonResponse({'session_id': session.id, 'url': session.url})


@login_required
@require_POST
def start_checkout(request):
    """In-app purchase for an existing organization: another round, or a first subscription."""
    organization = getattr(request, 'organization', None)
    profile = getattr(request.user, 'profile', None)
    if (not organization or profile is None or profile.organization_id != organization.pk
            or not request.user.has_perm('accounts.can_manage_organization')):
        messages.error(request, 'Only organization administrators can manage billing.')
        return redirect('settings')

    plan_type = request.POST.get('plan_type')
    if plan_type != 'single' and Subscription.objects.filter(organization=organization).exists():
        messages.error(request, 'This organization already has a subscription.')
        return redirect('settings')

    base_url = _base_url(request)
    try:
        session = _create_session(
            plan_type, base_url=base_url, cancel_url=f'{base_url}/dashboard/settings/',
            organization=organization, user=request.user,
        )
    except Exception:
        logger.exception('Error starting in-app checkout')
        messages.error(request, 'Could not start checkout. Please try again.')
        return redirect('settings')
    return redirect(session.url)


@require_POST
@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events"""

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    # Log incoming webhook
    logger.info(f"[STRIPE WEBHOOK] Received webhook request")
    logger.info(f"[STRIPE WEBHOOK] Signature header present: {bool(sig_header)}")
    logger.info(f"[STRIPE WEBHOOK] Payload size: {len(payload)} bytes")
    logger.info(f"[STRIPE WEBHOOK] Webhook secret configured: {bool(settings.STRIPE_WEBHOOK_SECRET)}")
    logger.info(f"[STRIPE WEBHOOK] Webhook secret length: {len(settings.STRIPE_WEBHOOK_SECRET) if settings.STRIPE_WEBHOOK_SECRET else 0}")

    try:
        # ponytail: .to_dict() because StripeObject stopped being a dict in stripe>=8
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        ).to_dict()
        logger.info(f"[STRIPE WEBHOOK] ✓ Signature verification successful")
        logger.info(f"[STRIPE WEBHOOK] Event type: {event['type']}")
        logger.info(f"[STRIPE WEBHOOK] Event ID: {event.get('id', 'N/A')}")
    except ValueError as e:
        logger.error(f"[STRIPE WEBHOOK] ✗ Invalid payload: {str(e)}")
        return HttpResponse(status=400)
    except stripe._error.SignatureVerificationError as e:
        logger.error(f"[STRIPE WEBHOOK] ✗ Signature verification failed: {str(e)}")
        logger.error(f"[STRIPE WEBHOOK] Signature header: {sig_header[:50] if sig_header else 'None'}...")
        logger.error(f"[STRIPE WEBHOOK] Secret starts with: {settings.STRIPE_WEBHOOK_SECRET[:10] if settings.STRIPE_WEBHOOK_SECRET else 'None'}...")
        return HttpResponse(status=400)

    # Handle the event
    try:
        if event['type'] == 'checkout.session.completed':
            logger.info(f"[STRIPE WEBHOOK] Processing checkout.session.completed")
            session = event['data']['object']
            fulfil_checkout(session)
            logger.info(f"[STRIPE WEBHOOK] ✓ Successfully processed checkout.session.completed")

        elif event['type'] == 'customer.subscription.updated':
            logger.info(f"[STRIPE WEBHOOK] Processing customer.subscription.updated")
            subscription = event['data']['object']
            handle_subscription_updated(subscription)
            logger.info(f"[STRIPE WEBHOOK] ✓ Successfully processed customer.subscription.updated")

        elif event['type'] == 'customer.subscription.deleted':
            logger.info(f"[STRIPE WEBHOOK] Processing customer.subscription.deleted")
            subscription = event['data']['object']
            handle_subscription_deleted(subscription)
            logger.info(f"[STRIPE WEBHOOK] ✓ Successfully processed customer.subscription.deleted")

        elif event['type'] == 'invoice.payment_failed':
            logger.info(f"[STRIPE WEBHOOK] Processing invoice.payment_failed")
            invoice = event['data']['object']
            handle_payment_failed(invoice)
            logger.info(f"[STRIPE WEBHOOK] ✓ Successfully processed invoice.payment_failed")
        else:
            logger.warning(f"[STRIPE WEBHOOK] Unhandled event type: {event['type']}")

    except Exception:
        logger.exception("[STRIPE WEBHOOK] ✗ Error processing event %s", event['type'])
        # 500 so Stripe retries. Every handler is idempotent, and a failed
        # fulfilment leaves nothing behind.
        return HttpResponse(status=500)

    logger.info(f"[STRIPE WEBHOOK] ✓ Webhook processing complete")
    return HttpResponse(status=200)


def handle_subscription_updated(stripe_subscription):
    """Update subscription status"""
    try:
        subscription = Subscription.objects.get(
            stripe_subscription_id=stripe_subscription['id']
        )
        start, end = _period(stripe_subscription)
        subscription.status = stripe_subscription['status']
        subscription.current_period_start = _ts(start)
        subscription.current_period_end = _ts(end)
        subscription.cancel_at_period_end = stripe_subscription.get('cancel_at_period_end', False)
        subscription.save()
    except Subscription.DoesNotExist:
        pass


def handle_subscription_deleted(stripe_subscription):
    """Mark subscription as canceled"""
    try:
        subscription = Subscription.objects.get(
            stripe_subscription_id=stripe_subscription['id']
        )
        subscription.status = 'canceled'
        subscription.canceled_at = timezone.now()
        subscription.save()
    except Subscription.DoesNotExist:
        pass


def handle_payment_failed(invoice):
    """Handle failed payment"""
    stripe_customer_id = invoice['customer']
    try:
        subscription = Subscription.objects.get(stripe_customer_id=stripe_customer_id)
        subscription.status = 'past_due'
        subscription.save()
        # TODO: Send payment failed email
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
        messages.info(request, "Payment received. We're finishing your setup; "
                               "you'll get an email shortly.")
        return redirect('login')

    if fulfilment is None:
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
        messages.success(request, 'Payment received. Your purchase has been added to your account.')
        return redirect('admin_dashboard' if signed_in else 'login')

    if fulfilment.outcome == 'rejected_existing_account':
        messages.error(request, 'This email address already has an account. The new subscription '
                                'was cancelled and nothing was charged. Sign in and choose a plan '
                                'under Settings.')
    else:
        messages.error(request, 'This organization already has a subscription. The new one was '
                                'cancelled and nothing was charged.')
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


@login_required
def billing_portal(request):
    """Redirect to Stripe billing portal for subscription management"""
    try:
        # Get user's organization
        if not hasattr(request.user, 'profile'):
            return redirect('settings')

        organization = request.user.profile.organization

        # Get subscription
        subscription = organization.subscription
        if not subscription:
            return redirect('settings')

        # Create billing portal session
        session = stripe.billing_portal.Session.create(
            customer=subscription.stripe_customer_id,
            return_url=f"{settings.SITE_URL}/dashboard/settings/",
        )

        return redirect(session.url)

    except Exception as e:
        logger.exception("Error creating billing portal session")
        return redirect('settings')
