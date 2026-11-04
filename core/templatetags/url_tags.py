from django import template

from core.url import get_absolute_url

register = template.Library()

# {% absolute_url 'reviews:feedback_form' token.token %}: like {% url %}, but on SITE_DOMAIN
register.simple_tag(get_absolute_url, name='absolute_url')
