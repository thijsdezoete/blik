import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name='to_json')
def to_json(value):
    """
    Convert a Python object to JSON for use in JavaScript

    Note: json.dumps() already escapes HTML/JS special characters like <, >, &
    so the output is safe for embedding in <script> tags or HTML attributes.
    We don't use mark_safe() because that would bypass Django's template
    auto-escaping. Instead, use this filter with |safe only in controlled contexts.
    """
    return json.dumps(value)
