from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    if dictionary is None:
        return None
    if not isinstance(dictionary, dict):
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


@register.filter
def percentage(value, total):
    """Calculate percentage"""
    try:
        if total == 0:
            return 0
        return round((float(value) / float(total)) * 100)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


@register.filter
def sort_by_frequency(distribution):
    """Sort distribution dict by count (descending)"""
    if not distribution:
        return []
    return sorted(distribution.items(), key=lambda x: x[1], reverse=True)


@register.filter
def get_rating_label(question_config, rating_value):
    """Get label for a rating value from question config"""
    try:
        labels = question_config.get('labels', {})
        return labels.get(str(int(rating_value)), '')
    except (ValueError, TypeError, AttributeError):
        return ''


@register.filter
def count_value(lst, value):
    """Count occurrences of value in list"""
    try:
        return lst.count(value)
    except (AttributeError, TypeError):
        return 0


@register.filter
def personalize(text, name):
    """Replace 'This person' / 'this person' with the reviewee's first name."""
    if not name:
        return text
    first_name = name.split()[0] if name else "This person"
    text = text.replace("This person", first_name)
    text = text.replace("this person", first_name)
    return text


@register.filter
def sort_categories(categories):
    """Sort categories dict with self first, then standard order"""
    if not categories:
        return []

    category_order = ['self', 'peer', 'manager', 'direct_report']
    result = []

    # Add categories in standard order
    for cat in category_order:
        if cat in categories:
            result.append((cat, categories[cat]))

    # Add any remaining categories
    for cat, score in categories.items():
        if cat not in category_order:
            result.append((cat, score))

    return result
