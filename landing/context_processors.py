"""
Context processors for landing app.

Provides URL namespace handling for templates that work in both
standalone landing container and main app contexts.
"""
from django.conf import settings


def url_namespace(request):
    """
    Provide URL namespace prefix for landing URLs.

    In standalone landing container: '' (no namespace)
    In main app: 'landing:' (namespaced)

    Detection is based on ROOT_URLCONF setting.
    """
    # Check if we're in standalone landing container or main app
    is_standalone = getattr(settings, 'ROOT_URLCONF', '') == 'landing_urls'

    return {
        'landing_ns': '' if is_standalone else 'landing:',
    }
