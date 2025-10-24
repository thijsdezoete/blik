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
    """Privacy/air-gapped landing page for professional services."""
    context = {
        'site_name': settings.SITE_NAME,
        'site_domain': settings.SITE_DOMAIN,
        'site_protocol': settings.SITE_PROTOCOL,
    }
    return render(request, 'landing/privacy.html', context)
