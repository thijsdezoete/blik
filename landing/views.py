from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
from django.urls import reverse
from .seo import generate_og_image


def index(request):
    """SEO-optimized landing page for Blik."""
    from .review_api import get_review_data_from_api

    # Fetch review data from main app API (works across containers)
    rating_data = get_review_data_from_api()

    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
        'site_description': settings.SITE_DESCRIPTION,
        'site_keywords': settings.SITE_KEYWORDS,
        'rating_data': rating_data,
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
    from .review_api import get_review_data_from_api

    # Fetch review data from main app API (works across containers)
    rating_data = get_review_data_from_api()

    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
        'rating_data': rating_data,
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


def agency_levels(request):
    """5 Levels of Agency framework page for high-agency workplace culture."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/agency_levels.html', context)


def performance_matrix(request):
    """Performance Matrix page combining Dreyfus Model with Agency Levels."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/performance_matrix.html', context)


def signup(request):
    """Signup page with Stripe checkout integration."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        'stripe_price_id_saas': settings.STRIPE_PRICE_ID_SAAS,
        'stripe_price_id_enterprise': settings.STRIPE_PRICE_ID_ENTERPRISE,
        # main_app_url now provided by context processor
    }
    return render(request, 'landing/signup.html', context)


def vs_lattice(request):
    """Blik vs Lattice comparison page."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/vs_lattice.html', context)


def vs_culture_amp(request):
    """Blik vs Culture Amp comparison page."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/vs_culture_amp.html', context)


def vs_15five(request):
    """Blik vs 15Five comparison page."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/vs_15five.html', context)


def why_blik(request):
    """Why Blik exists - comprehensive differentiation page."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/why_blik.html', context)


def developers(request):
    """Developer-focused landing page with API documentation and quickstart."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
        # main_app_url and API URLs now provided by context processor
    }
    return render(request, 'landing/developers.html', context)
