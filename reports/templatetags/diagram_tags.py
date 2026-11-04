from django import template

STAGE_NUMBERS = {'novice': 1, 'advanced_beginner': 2, 'competent': 3, 'proficient': 4, 'expert': 5}

register = template.Library()


@register.filter
def stage_opacity(number, current):
    """'' for the current stage (or when none is set), '0.3' for every other one.

    `current` is a Dreyfus stage key or an agency level "1".."5". The opacity is written onto the
    SVG groups because WeasyPrint ignores the page CSS that does this on the web.
    """
    current_number = STAGE_NUMBERS.get(current) or (int(current) if str(current).isdigit() else None)
    if current_number is None or current_number == number:
        return ''
    return '0.3'
