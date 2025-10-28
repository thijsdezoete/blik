from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
from django.urls import reverse
from .seo import generate_og_image


def index(request):
    """SEO-optimized landing page for Blik."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
        'site_description': settings.SITE_DESCRIPTION,
        'site_keywords': settings.SITE_KEYWORDS,
    }
    return render(request, 'landing/index.html', context)


def og_image(request):
    """Generate Open Graph image dynamically."""
    image_buffer = generate_og_image(
        title=settings.SITE_NAME,
        subtitle="Open Source 360° Feedback"
    )
    return HttpResponse(image_buffer.getvalue(), content_type='image/png')


def open_source(request):
    """Open source landing page for developer audience."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/open_source.html', context)


def dreyfus_model(request):
    """Dreyfus Model and competency framework explanation page."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/dreyfus_model.html', context)


def eu_tech(request):
    """EU/GDPR-focused landing page for European tech companies."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/eu_tech.html', context)


def privacy(request):
    """Air-gapped/privacy-focused landing page for professional services."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/privacy.html', context)


def privacy_policy(request):
    """Privacy policy page."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/privacy_policy.html', context)


def terms(request):
    """Terms of service page."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/terms.html', context)


def hr_managers(request):
    """HR manager focused landing page for growing teams (30-50 employees)."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/hr_managers.html', context)


def signup(request):
    """Signup page with Stripe checkout integration."""
    # Get main app URL from environment or use current host for local dev
    main_app_url = getattr(settings, 'MAIN_APP_URL', None)
    if not main_app_url or settings.DEBUG:
        # For local development, use the current request host
        scheme = 'https' if request.is_secure() else 'http'
        main_app_url = f"{scheme}://{request.get_host()}"

    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        'stripe_price_id_saas': settings.STRIPE_PRICE_ID_SAAS,
        'stripe_price_id_enterprise': settings.STRIPE_PRICE_ID_ENTERPRISE,
        'main_app_url': main_app_url,
    }
    return render(request, 'landing/signup.html', context)
