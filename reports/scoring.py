"""The 1 to 5 scale that reports and charts show the average of every scored question on.

This module imports nothing from the report services, so services.py and dreyfus_service.py can both import it.
"""


def _number(value, default):
    # A missing or empty number takes the default; 0 is a real lowest number (a slider from 0 to 10)
    return default if value is None else value


def score_range(question_data):
    """The lowest and highest score a question's answer can have, (low, high), or None when it has no range.

    question_data is a question as report data holds it: 'question_type', 'question_config' (None or missing in old
    reports) and 'options' ([{'id', 'label', 'weight'}]). A pick-several answer scores the sum of its picked weights,
    so its lowest is the sum of the negative weights and its highest the sum of the positive ones. A likert average
    is on the 1 to 5 scale already (see likert_score() in services.py) and has no range here.
    """

    config = question_data.get('question_config')

    if not isinstance(config, dict):
        return None

    question_type = question_data.get('question_type')

    if question_type in ('rating', 'scale'):
        low = _number(config.get('min'), 1)
        high = _number(config.get('max'), 5 if question_type == 'rating' else 100)
    elif question_type in ('single_choice', 'multiple_choice'):
        weights = [
            option.get('weight') for option in question_data.get('options') or []
            if isinstance(option.get('weight'), (int, float))
        ]

        if not weights:
            return None

        if question_type == 'single_choice':
            low, high = min(weights), max(weights)
        else:
            negative = [weight for weight in weights if weight < 0]
            positive = [weight for weight in weights if weight > 0]
            low = sum(negative) if negative else min(weights)
            high = sum(positive) if positive else max(weights)
    else:
        return None

    if high <= low:
        return None

    return low, high


def score_on_five(question_data, value):
    """value, an answer or average of the question, on the 1 to 5 scale; unchanged when the question has no range."""

    bounds = score_range(question_data)

    if bounds is None:
        return value

    low, high = bounds

    return 1 + (value - low) / (high - low) * 4
