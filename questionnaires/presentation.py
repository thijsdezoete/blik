"""Report capabilities for questionnaire selection, before any answers are collected."""

from math import isfinite

from django.utils.translation import gettext_lazy as _


def _is_number(value):
    return isinstance(value, (int, float)) and isfinite(value)


def questionnaire_report_features(questionnaire):
    """Describe visuals the current report can show, subject to sufficient answers.

    Keep these rules aligned with reports.services and reports.dreyfus_service.
    Related-manager iteration uses prefetched sections, questions and options;
    Questionnaire.translation_lookups() already includes those relations.
    """
    available = set()

    for section in questionnaire.sections.all():
        for question in section.questions.all():
            if question.question_type == 'text':
                available.add('written')
                continue

            config = question.config
            if not isinstance(config, dict):
                continue

            options = []
            if question.question_type in ('likert', 'single_choice', 'multiple_choice'):
                options = list(question.options.all())
            if question.question_type == 'rating' or options:
                available.add('distribution')

            # A likert answer scores by the position of its option, which takes two options (see likert_score)
            has_score = question.question_type in ('rating', 'scale') or (
                question.question_type == 'likert' and len(options) >= 2
            )
            has_nonzero_score = has_score
            if question.question_type in ('single_choice', 'multiple_choice') and config.get('scoring_enabled'):
                weights = [
                    option.weight for option in options if _is_number(option.weight)
                ]
                has_score = bool(weights)
                # The Dreyfus service ignores zero averages; charts still display them.
                has_nonzero_score = any(weight != 0 for weight in weights)

            if not has_score:
                continue

            chart_weight = config.get('chart_weight', 1)
            if not config.get('exclude_from_charts') and _is_number(chart_weight) and chart_weight > 0:
                available.add('radar')

            mapping = config.get('dreyfus_mapping')
            if not has_nonzero_score or not isinstance(mapping, dict):
                continue

            for dimension, feature in (('skill', 'dreyfus'), ('agency', 'agency')):
                weight = mapping.get(dimension)
                if dimension not in mapping and mapping.get('dimension') == dimension:
                    weight = mapping.get('weight', 1)
                if _is_number(weight) and weight != 0:
                    available.add(feature)

    # _dreyfus_profile.html renders the agency tab inside the skill-profile gate.
    if 'dreyfus' not in available:
        available.discard('agency')

    features = [
        {
            'key': 'radar',
            'label': _('Skills overview'),
            'description': _('Compare strengths across topics in a radar chart.'),
        },
        {
            'key': 'dreyfus',
            'label': _('Skill level'),
            'description': _('See the stage of skill development (Dreyfus model).'),
        },
        {
            'key': 'agency',
            'label': _('Initiative'),
            'description': _('Understand initiative and independence (agency model).'),
        },
        {
            'key': 'distribution',
            'label': _('Answer breakdown'),
            'description': _('See how responses are distributed for each question.'),
        },
        {
            'key': 'written',
            'label': _('Written feedback'),
            'description': _('Read comments and examples from reviewers.'),
        },
    ]
    return [feature for feature in features if feature['key'] in available]
