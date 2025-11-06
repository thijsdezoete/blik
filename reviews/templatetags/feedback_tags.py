from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    if dictionary is None:
        return None
    return dictionary.get(str(key))


@register.filter
def mul(value, arg):
    """Multiply the value by the argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def average(values):
    """Calculate average of a list of numbers"""
    try:
        numeric_values = [float(v) for v in values if v is not None]
        if numeric_values:
            return sum(numeric_values) / len(numeric_values)
        return 0
    except (ValueError, TypeError):
        return 0


@register.filter
def others_average(categories):
    """Calculate average of non-self categories in a dict"""
    try:
        if not categories:
            return 0
        others_scores = [float(v) for k, v in categories.items() if k != 'self' and v is not None]
        if others_scores:
            return sum(others_scores) / len(others_scores)
        return 0
    except (ValueError, TypeError, AttributeError):
        return 0


@register.filter
def subtract(value, arg):
    """Subtract arg from value"""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0
