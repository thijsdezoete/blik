"""
Custom template tags for landing app.

Provides namespace-aware URL reversal for templates that work in both
standalone landing container and main app contexts.
"""
from django import template
from django.conf import settings
from django.urls import reverse

register = template.Library()


@register.simple_tag
def landing_url(view_name):
    """
    Reverse a landing URL with appropriate namespace.

    In standalone landing container: reverse('index')
    In main app: reverse('landing:index')
    """
    is_standalone = getattr(settings, 'ROOT_URLCONF', '') == 'landing_urls'

    if is_standalone:
        return reverse(view_name)
    else:
        return reverse(f'landing:{view_name}')


@register.filter
def get_item(dictionary, key):
    """
    Template filter to get item from dict by key.

    Usage: {{ mydict|get_item:key }}
    Equivalent to: mydict[key] or mydict.get(key)
    """
    if dictionary is None:
        return None
    return dictionary.get(key)
