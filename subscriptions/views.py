import stripe
import json
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.shortcuts import redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from datetime import datetime, timezone as dt_timezone
from core.models import Organization
from .models import Plan, Subscription, OneTimeLoginToken

stripe.api_key = settings.STRIPE_SECRET_KEY


def send_welcome_email(organization, user, password):
    """Send welcome email with login credentials to new customer"""
    subject = f'Welcome to {settings.SITE_NAME} - Your Account is Ready'

    # Render email templates
    html_message = render_to_string('emails/welcome.html', {
        'organization': organization,
        'user': user,
        'password': password,
        'login_url': f'{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}/accounts/login/',
        'site_name': settings.SITE_NAME,
    })

    text_message = render_to_string('emails/welcome.txt', {
        'organization': organization,
        'user': user,
        'password': password,
        'login_url': f'{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}/accounts/login/',
        'site_name': settings.SITE_NAME,
    })

    try:
        send_mail(
            subject=subject,
            message=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
    except Exception as e:
        # Log error but don't fail the signup
        print(f"Failed to send welcome email to {user.email}: {e}")


@require_POST
@csrf_exempt
def create_checkout_session(request):
    """Create Stripe Checkout session"""
    try:
        data = json.loads(request.body)
        price_id = data.get('price_id')
        plan_type = data.get('plan_type')

        if not price_id or not plan_type:
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        # Build base URL from request for local dev, or use configured domain
        if settings.DEBUG:
            scheme = 'https' if request.is_secure() else 'http'
            base_url = f"{scheme}://{request.get_host()}"
        else:
            base_url = settings.MAIN_APP_URL

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f'{base_url}/api/stripe/checkout-success/?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{base_url}/landing/signup/?canceled=true',
            subscription_data={
                'trial_period_days': 14,
            },
            metadata={
                'plan_type': plan_type,
            },
        )

        return JsonResponse({'session_id': session.id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_POST
@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events"""
    import logging
    logger = logging.getLogger(__name__)

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    # Log incoming webhook
    logger.info(f"[STRIPE WEBHOOK] Received webhook request")
    logger.info(f"[STRIPE WEBHOOK] Signature header present: {bool(sig_header)}")
    logger.info(f"[STRIPE WEBHOOK] Payload size: {len(payload)} bytes")
    logger.info(f"[STRIPE WEBHOOK] Webhook secret configured: {bool(settings.STRIPE_WEBHOOK_SECRET)}")
    logger.info(f"[STRIPE WEBHOOK] Webhook secret length: {len(settings.STRIPE_WEBHOOK_SECRET) if settings.STRIPE_WEBHOOK_SECRET else 0}")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
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
            handle_checkout_session_completed(session)
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

    except Exception as e:
        logger.error(f"[STRIPE WEBHOOK] ✗ Error processing event {event['type']}: {str(e)}")
        logger.exception(e)
        # Still return 200 to prevent Stripe from retrying
        return HttpResponse(status=200)

    logger.info(f"[STRIPE WEBHOOK] ✓ Webhook processing complete")
    return HttpResponse(status=200)


def handle_checkout_session_completed(session):
    """
    Handle successful checkout - create organization and user
    This is the PRIMARY registration path for new customers
    """
    # Extract metadata from checkout session
    customer_email = session['customer_details']['email']
    customer_name = session['customer_details']['name']
    plan_type = session['metadata'].get('plan_type')  # 'saas' or 'enterprise'

    # Get Stripe subscription details
    stripe_customer_id = session['customer']
    stripe_subscription_id = session['subscription']

    # Check if subscription already exists (idempotency)
    if Subscription.objects.filter(stripe_subscription_id=stripe_subscription_id).exists():
        print(f"Subscription {stripe_subscription_id} already exists, skipping creation")
        return

    stripe_subscription = stripe.Subscription.retrieve(stripe_subscription_id)

    # Get or create plan
    try:
        plan = Plan.objects.get(plan_type=plan_type)
    except Plan.DoesNotExist:
        print(f"ERROR: Plan type '{plan_type}' not found. Please create plans in admin.")
        return

    # Check if user already exists
    existing_user = User.objects.filter(email=customer_email).first()
    if existing_user:
        print(f"WARNING: User {customer_email} already exists. Linking to existing user.")
        user = existing_user
        password = None  # Don't generate new password for existing user
    else:
        # Create admin user
        username = customer_email.split('@')[0]
        # Ensure username is unique
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        from django.contrib.auth.hashers import make_password
        import secrets
        import string

        # Generate random password
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for _ in range(16))

        # Create user as staff (organization admin)
        user = User.objects.create_user(
            username=username,
            email=customer_email,
            password=password,
            is_staff=True,  # Organization admin can manage their org
            is_active=True
        )

    # Create organization
    org = Organization.objects.create(
        name=customer_name,
        email=customer_email
    )

    # Create user profile
    from accounts.models import UserProfile
    UserProfile.objects.create(
        user=user,
        organization=org,
        can_create_cycles_for_others=True
    )

    # Create subscription
    # For trial subscriptions, use trial dates as current period
    # For active subscriptions, use billing period dates
    sub_dict = dict(stripe_subscription)

    current_start = sub_dict.get('current_period_start') or sub_dict.get('trial_start') or sub_dict.get('created')
    current_end = sub_dict.get('current_period_end') or sub_dict.get('trial_end')

    Subscription.objects.create(
        organization=org,
        plan=plan,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        status=sub_dict.get('status', 'trialing'),
        current_period_start=datetime.fromtimestamp(current_start, tz=dt_timezone.utc),
        current_period_end=datetime.fromtimestamp(current_end, tz=dt_timezone.utc),
        trial_start=datetime.fromtimestamp(sub_dict['trial_start'], tz=dt_timezone.utc) if sub_dict.get('trial_start') else None,
        trial_end=datetime.fromtimestamp(sub_dict['trial_end'], tz=dt_timezone.utc) if sub_dict.get('trial_end') else None,
    )

    # Create one-time login token for auto-login
    from .models import OneTimeLoginToken
    from datetime import timedelta

    login_token = OneTimeLoginToken.objects.create(
        user=user,
        expires_at=timezone.now() + timedelta(hours=1)
    )

    # Send welcome email (only if new user with password)
    if password:
        send_welcome_email(org, user, password)

    print(f"Created organization '{org.name}' with auto-login token: {login_token.token}")


def handle_subscription_updated(stripe_subscription):
    """Update subscription status"""
    try:
        subscription = Subscription.objects.get(
            stripe_subscription_id=stripe_subscription['id']
        )
        subscription.status = stripe_subscription['status']
        subscription.current_period_start = datetime.fromtimestamp(stripe_subscription['current_period_start'], tz=timezone.utc)
        subscription.current_period_end = datetime.fromtimestamp(stripe_subscription['current_period_end'], tz=timezone.utc)
        subscription.cancel_at_period_end = stripe_subscription['cancel_at_period_end']
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
    """
    Handle Stripe checkout success redirect.
    Wait for webhook to create account, then redirect to auto-login.
    """
    import logging
    logger = logging.getLogger(__name__)

    session_id = request.GET.get('session_id')
    logger.info(f"[CHECKOUT SUCCESS] Received session_id: {session_id}")

    if not session_id:
        logger.warning("[CHECKOUT SUCCESS] No session_id provided, redirecting to login")
        return redirect('login')

    try:
        # Retrieve the session to get customer email
        session = stripe.checkout.Session.retrieve(session_id)
        customer_email = session['customer_details']['email']
        logger.info(f"[CHECKOUT SUCCESS] Customer email: {customer_email}")
        logger.info(f"[CHECKOUT SUCCESS] Session status: {session.get('status')}")
        logger.info(f"[CHECKOUT SUCCESS] Payment status: {session.get('payment_status')}")

        # Poll for the user to be created (webhook might still be processing)
        import time
        max_attempts = 10
        for attempt in range(max_attempts):
            logger.info(f"[CHECKOUT SUCCESS] Poll attempt {attempt + 1}/{max_attempts}")
            user = User.objects.filter(email=customer_email).first()
            if user:
                logger.info(f"[CHECKOUT SUCCESS] User found: {user.username}")
                # Get the latest login token for this user
                token = OneTimeLoginToken.objects.filter(
                    user=user,
                    used=False,
                    expires_at__gt=timezone.now()
                ).order_by('-created_at').first()

                if token:
                    logger.info(f"[CHECKOUT SUCCESS] Login token found, redirecting to auto-login")
                    return redirect('subscriptions:auto_login', token=token.token)
                else:
                    logger.warning(f"[CHECKOUT SUCCESS] User exists but no valid login token found")

            if attempt < max_attempts - 1:
                time.sleep(1)  # Wait 1 second before retrying

        # If we get here, something went wrong
        logger.error(f"[CHECKOUT SUCCESS] Timeout waiting for webhook - user not created for {customer_email}")
        logger.error(f"[CHECKOUT SUCCESS] This means the webhook never processed or failed")
        return redirect('login')

    except Exception as e:
        logger.error(f"[CHECKOUT SUCCESS] Error: {e}")
        logger.exception(e)
        return redirect('login')


def auto_login(request, token):
    """Auto-login user with one-time token"""
    try:
        login_token = OneTimeLoginToken.objects.get(
            token=token,
            used=False,
            expires_at__gt=timezone.now()
        )

        # Mark token as used
        login_token.used = True
        login_token.save()

        # Log the user in
        login(request, login_token.user, backend='django.contrib.auth.backends.ModelBackend')

        # Redirect to setup wizard for onboarding
        return redirect('setup_organization')

    except OneTimeLoginToken.DoesNotExist:
        return redirect('login')


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
            return_url=f"{request.scheme}://{request.get_host()}/dashboard/settings/",
        )

        return redirect(session.url)

    except Exception as e:
        print(f"Error creating billing portal session: {e}")
        return redirect('settings')
