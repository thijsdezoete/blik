from django import template
from django.utils.translation import gettext_lazy as _

from questionnaires.models import Question
from questionnaires.placeholders import personalize as personalize_text
from reports.report_texts import RATING_RANGES
from reports.services import get_rating_key
from reviews.models import CATEGORY_ORDER

register = template.Library()

CATEGORY_LABELS = {
    'self': _('Self'),
    'peer': _('Peer'),
    'manager': _('Manager'),
    'direct_report': _('Direct Report'),
}


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    if dictionary is None:
        return None
    if not isinstance(dictionary, dict):
        return None
    return dictionary.get(str(key))


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
    """Calculate average of non-self categories in a dict, without groups hidden for anonymity"""
    try:
        if not categories:
            return 0
        others_scores = [
            float(v) for k, v in categories.items()
            if k != 'self' and v is not None and not isinstance(v, dict)
        ]
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
def report_options(question_data):
    """Answer options of a report question as [{'id', 'label', 'weight'}, ...].

    Reports generated before answer options existed count their answers by label and carry no 'options'. For those the
    label doubles as the id, so their stored counts still line up.
    """

    if options := question_data.get('options'):
        return options

    config = question_data.get('question_config') or {}
    labels = config.get('scale') or config.get('choices') or []
    weights = config.get('weights') or []

    return [
        {'id': label, 'label': label, 'weight': weights[index] if index < len(weights) else None}
        for index, label in enumerate(labels)
    ]


def distribution_key(option):
    """The key a report distribution counts an option under: its id as text."""

    option_id = option['id']

    return f'{option_id}'


@register.filter
def option_count(distribution, option):
    """How many answers in a report distribution chose the option."""

    return (distribution or {}).get(distribution_key(option), 0)


@register.filter
def option_label(key, question_data):
    """Label of the option a report distribution key stands for, falling back to the key itself."""

    for option in report_options(question_data):
        if distribution_key(option) == key:
            return option['label']

    return key


@register.filter
def option_weights(question_data):
    """The weights of a report question's options, in their order."""

    return [option['weight'] for option in report_options(question_data) if option['weight'] is not None]


@register.filter
def likert_positive_count(distribution, options):
    """Answers in the two highest options of a likert scale.

    Counted by position rather than by label, so custom scales and reworded or translated labels are summarised too.
    """

    return sum(option_count(distribution, option) for option in options[-2:])


@register.filter
def rating_key(score):
    """The overall rating of an average score; reports colour a score by it."""

    return get_rating_key(score)


@register.filter
def rating_with_range(score):
    """The overall rating of an average score, with the scores it covers."""

    return RATING_RANGES[get_rating_key(score)]


@register.filter
def report_labels(question_data):
    """Rating labels of a report question; reports generated before Question.labels existed keep them in the config."""

    config = question_data.get('question_config') or {}

    return question_data.get('labels') or config.get('labels') or {}


@register.filter
def get_rating_label(question_data, rating_value):
    """Get label for a rating value of a report question"""

    labels = report_labels(question_data)

    try:
        return labels.get(str(int(rating_value)), '')
    except (ValueError, TypeError):
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
    """The text with the reviewee's first name, see questionnaires/placeholders.py."""
    return personalize_text(text, name)


@register.filter
def category_label(category):
    """Short label for a feedback category code"""
    return CATEGORY_LABELS.get(category, category)


@register.filter
def question_type_label(question_type):
    """Label for a question type code"""
    return dict(Question.QUESTION_TYPES).get(question_type, question_type)


@register.filter
def sort_categories(categories):
    """Sort categories dict with self first, then standard order"""
    if not categories:
        return []

    category_order = CATEGORY_ORDER
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
