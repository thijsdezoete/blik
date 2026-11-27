"""
The texts of a report, in the active language.

Reports of the current schema store codes and numbers. with_texts() adds the texts the report templates show, under the
keys in which reports of schema 1 stored them in English. The texts of the questionnaire that the report stores in its
source language are replaced by their translations where there are any. Reports of schema 1 keep their English texts.
"""

import copy

from django.db.models import prefetch_related_objects
from django.utils import translation
from django.utils.formats import number_format
from django.utils.translation import gettext_lazy as _

from questionnaires.placeholders import personalize

from .dreyfus_service import (
    DREYFUS_STAGES,
    agency_profile_with_texts,
    development_plan_with_texts,
    quadrant_with_texts,
    skill_profile_with_texts,
)
from .services import (
    GAP_IMPOSTER_SYNDROME,
    GAP_OVERCONFIDENCE,
    RATING_DEVELOPING,
    RATING_EXCELLENT,
    RATING_NEEDS_SUPPORT,
    RATING_OUTSTANDING,
    RATING_STRONG,
    REPORT_SCHEMA,
    TREND_DOWN,
    TREND_SLIGHT_DOWN,
    TREND_SLIGHT_UP,
    TREND_STABLE,
    TREND_UP,
)

# Symbol and label of a trend by its direction
TRENDS = {
    TREND_UP: ('↑', _('Improved')),
    TREND_SLIGHT_UP: ('↗', _('Slightly improved')),
    TREND_STABLE: ('→', _('Stable')),
    TREND_SLIGHT_DOWN: ('↘', _('Slightly declined')),
    TREND_DOWN: ('↓', _('Declined')),
}

# Message and interpretation of a perception gap by its type
PERCEPTION_GAPS = {
    GAP_IMPOSTER_SYNDROME: (
        _("Self-assessment (%(self)s) significantly lower than others' perception (%(others)s)"),
        _('Strong performance but may undervalue own contributions'),
    ),
    GAP_OVERCONFIDENCE: (
        _("Self-assessment (%(self)s) higher than others' perception (%(others)s)"),
        _('Opportunity to align self-perception with team feedback'),
    ),
}

# The overall ratings with the average scores they cover
RATING_RANGES = {
    RATING_OUTSTANDING: _('Outstanding (4.5+)'),
    RATING_EXCELLENT: _('Excellent (4.0-4.4)'),
    RATING_STRONG: _('Strong (3.5-3.9)'),
    RATING_DEVELOPING: _('Developing (3.0-3.4)'),
    RATING_NEEDS_SUPPORT: _('Needs Support (below 3.0)'),
}

RATINGS = {
    RATING_OUTSTANDING: _('Outstanding'),
    RATING_EXCELLENT: _('Excellent'),
    RATING_STRONG: _('Strong'),
    RATING_DEVELOPING: _('Developing'),
    RATING_NEEDS_SUPPORT: _('Needs Support'),
}


def stage_key(name):
    """The key of the Dreyfus stage that a report of schema 1 names in English."""

    with translation.override('en'):
        keys = {str(stage['name']): stage['key'] for stage in DREYFUS_STAGES.values()}

    return keys.get(name)


def get_texts(parts, part_id, language):
    """The translated texts of a questionnaire part; none for a part deleted since the report was generated."""

    part = parts.get(part_id)

    return part.get_translated_texts(language) if part else {}


def in_order(stored, order):
    """
    stored in the order of the keys in order; a key that order lacks (a part deleted since) comes last.

    PostgreSQL does not keep the order of the keys of a stored object: it gives them back by length and then by bytes.
    """

    place = {str(key): index for index, key in enumerate(order)}

    return dict(sorted(stored.items(), key=lambda item: place.get(item[0], len(place))))


def rename_sections(by_title, titles):
    """by_title with its section titles replaced by those in titles, in the order of titles."""

    return {titles.get(title, title): value for title, value in in_order(by_title, titles).items()}


def translate_questionnaire_texts(data, questionnaire):
    """Replace the questionnaire texts stored in data with their translations into the active language."""

    language = translation.get_language()
    prefetch_related_objects([questionnaire], *questionnaire.translation_lookups())
    sections = {section.id: section for section in questionnaire.sections.all()}
    questions = {question.id: question for section in sections.values() for question in section.questions.all()}
    options = {option.id: option for question in questions.values() for option in question.options.all()}
    titles = {}

    # The order of the questionnaire as it is now: a report stores no order of its own
    if 'by_section' in data:
        data['by_section'] = in_order(data['by_section'], sections)

    for section_id, section_data in data.get('by_section', {}).items():
        title = get_texts(sections, int(section_id), language).get('title', section_data['title'])
        titles[section_data['title']] = title
        section_data['title'] = title
        section_data['questions'] = in_order(section_data['questions'], questions)

        for question_id, question_data in section_data['questions'].items():
            texts = get_texts(questions, int(question_id), language)
            labels = texts.get('labels', {})
            question_data['question_text'] = texts.get('question_text', question_data['question_text'])
            question_data['labels'] = {key: labels.get(key, label) for key, label in question_data['labels'].items()}
            question_data['options'] = [
                {**option, 'label': get_texts(options, option['id'], language).get('label', option['label'])}
                for option in question_data['options']
            ]

    # Summaries, trends, benchmarks and charts are keyed by the section titles
    insights = data.get('insights') or {}
    comparison = data.get('comparison') or {}
    charts = data.get('charts') or {}

    for key in ['section_summary', 'peer_benchmarks']:
        if by_title := data.get(key):
            data[key] = rename_sections(by_title, titles)

    if section_trends := comparison.get('section_trends'):
        comparison['section_trends'] = rename_sections(section_trends, titles)

    if section_scores := charts.get('section_scores'):
        charts['section_scores'] = rename_sections(section_scores, titles)

    for area in [*insights.get('strengths', []), *insights.get('development_areas', [])]:
        area['area'] = titles.get(area['area'], area['area'])

    for item in (insights.get('development_plan') or {}).get('action_items', []):
        action_items = get_texts(questions, item['question_id'], language).get('action_items', {})
        item['text'] = action_items.get(item['key'], item['text'])


def personalize_texts(data, name):
    """Put the reviewee's first name into the question texts and action items stored in data."""

    for section_data in data.get('by_section', {}).values():
        for question_data in section_data['questions'].values():
            question_data['question_text'] = personalize(question_data['question_text'], name)

    insights = data.get('insights') or {}

    for item in (insights.get('development_plan') or {}).get('action_items', []):
        item['text'] = personalize(item['text'], name)


def with_texts(report_data, questionnaire, reviewee_name=None):
    """
    A copy of report_data with the texts its codes stand for, its questionnaire texts in the active language and the
    reviewee's first name in them.
    """

    data = copy.deepcopy(report_data)
    insights = data.get('insights') or {}
    skill_profile = insights.get('skill_profile')

    if data.get('schema') != REPORT_SCHEMA:
        if skill_profile:
            skill_profile['stage_key'] = stage_key(skill_profile.get('skill_stage'))

        return data

    translate_questionnaire_texts(data, questionnaire)
    personalize_texts(data, reviewee_name)
    comparison = data.get('comparison') or {}
    trends = [comparison.get('overall_trend'), *(comparison.get('section_trends') or {}).values()]

    for trend in trends:
        if trend:
            symbol, label = TRENDS[trend['direction']]
            trend.update(symbol=symbol, label=str(label))

    for gap in insights.get('perception_gaps') or []:
        message, interpretation = PERCEPTION_GAPS[gap['type']]
        # number_format() cuts off further decimals instead of rounding them
        scores = {
            'self': number_format(round(gap['self_score'], 1), 1),
            'others': number_format(round(gap['others_score'], 1), 1),
        }
        gap.update(message=message % scores, interpretation=str(interpretation))

    if sentiment := insights.get('overall_sentiment'):
        sentiment['rating'] = str(RATINGS[sentiment['rating']])

    if skill_profile:
        insights['skill_profile'] = skill_profile_with_texts(skill_profile)

    if agency_profile := insights.get('agency_profile'):
        insights['agency_profile'] = agency_profile_with_texts(agency_profile)

    if quadrant := insights.get('dreyfus_quadrant'):
        insights['dreyfus_quadrant'] = quadrant_with_texts(quadrant)

    if (plan := insights.get('development_plan')) and skill_profile:
        insights['development_plan'] = development_plan_with_texts(plan, skill_profile)

    return data
