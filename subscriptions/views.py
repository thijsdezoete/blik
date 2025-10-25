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
from datetime import datetime
from core.models import Organization
from .models import Plan, Subscription

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

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f'{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}/landing/?success=true',
            cancel_url=f'{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}/landing/?canceled=true',
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
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_session_completed(session)

    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        handle_subscription_updated(subscription)

    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        handle_subscription_deleted(subscription)

    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        handle_payment_failed(invoice)

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
        # Update to staff if not already
        if not user.is_staff:
            user.is_staff = True
            user.save()
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

        password = User.objects.make_random_password(length=16)
        user = User.objects.create_user(
            username=username,
            email=customer_email,
            password=password,
            is_staff=True
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
    Subscription.objects.create(
        organization=org,
        plan=plan,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        status=stripe_subscription['status'],
        current_period_start=datetime.fromtimestamp(stripe_subscription['current_period_start'], tz=timezone.utc),
        current_period_end=datetime.fromtimestamp(stripe_subscription['current_period_end'], tz=timezone.utc),
        trial_start=datetime.fromtimestamp(stripe_subscription['trial_start'], tz=timezone.utc) if stripe_subscription.get('trial_start') else None,
        trial_end=datetime.fromtimestamp(stripe_subscription['trial_end'], tz=timezone.utc) if stripe_subscription.get('trial_end') else None,
    )

    # Send welcome email (only if new user with password)
    if password:
        send_welcome_email(org, user, password)


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
