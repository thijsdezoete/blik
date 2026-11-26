"""
The save logic of the questionnaire editor.

The editor page posts the fields of one question, or one weight, and shows the result. These functions check what was
posted and store it. Their EditorError texts are shown to the creator.
"""

from math import isfinite

from django.db import transaction
from django.db.models import Count, Max
from django.utils import translation
from django.utils.translation import gettext as _

from reviews.models import Response

from .action_items import add_action_item_keys
from .answer_options import DEFAULT_LIKERT_SCALE, DEFAULT_RATING_LABELS, save_options
from .models import Question

WEIGHTS = (0, 0.5, 1, 1.5, 2)
MODELS = ('skill', 'agency')

RATING_COUNTS = range(2, 8)
DID_NOT_OBSERVE_TYPES = ('rating', 'likert')


class EditorError(Exception):
    """A posted value the editor cannot store. Its text is shown to the creator."""


def get_default_labels(questionnaire):
    """The default likert scale and rating labels of a new question, in the questionnaire's source language."""

    with translation.override(questionnaire.source_language):
        likert_scale = [f'{label}' for label in DEFAULT_LIKERT_SCALE]
        rating_labels = {key: f'{label}' for key, label in DEFAULT_RATING_LABELS.items()}

    return likert_scale, rating_labels


def posted_labels(post, question_type, count=len(DEFAULT_RATING_LABELS)):
    """The rating labels of the values 1 to count, or the scale labels, the question editor posted, without the empty
    ones."""

    if question_type == 'rating':
        fields = {f'{value}': f'rating_label_{value}' for value in range(1, count + 1)}
    elif question_type == 'scale':
        fields = {'min': 'scale_min_label', 'max': 'scale_max_label'}
    else:
        return {}

    labels = {key: post.get(field, '').strip() for key, field in fields.items()}

    return {key: label for key, label in labels.items() if label}


def posted_descriptions(post, question_type, count=len(DEFAULT_RATING_LABELS)):
    """The descriptions of the rating values 1 to count the question editor posted, without the empty ones."""

    if question_type != 'rating' or post.get('rating_descriptions') != 'on':
        return {}

    descriptions = {f'{value}': post.get(f'rating_description_{value}', '').strip() for value in range(1, count + 1)}

    return {key: text for key, text in descriptions.items() if text}


def posted_option_rows(post, prefix, with_weights=False):
    """The answer options the question editor posted, as [(id or None, label, weight), ...].

    Each row posts the id of its option (empty for a new one), its label and, for choice questions, its weight. Rows
    without a label are dropped. Raises ValueError for a weight that is not a number.
    """

    ids = post.getlist(f'{prefix}_option_id')
    labels = post.getlist(f'{prefix}_option_label')
    weights = post.getlist(f'{prefix}_option_weight') if with_weights else [''] * len(labels)
    rows = []

    for posted_id, label, weight in zip(ids, labels, weights):
        if label := label.strip():
            option_id = int(posted_id) if posted_id.isdigit() else None
            rows.append((option_id, label, float(weight) if with_weights else None))

    return rows


def posted_action_items(post, question=None, prefix='action_items'):
    """The action items posted as <prefix>[<i>][text|threshold|key|stages][], in the order of i.

    Items without a text are dropped. A posted key is kept only when the question already has an item with it, so the
    client cannot set keys of its own. Raises ValueError for a threshold or stage that is not a number.
    """

    known_keys = {item.get('key') for item in question.action_items if isinstance(item, dict)} if question else set()
    indices = {
        name.split('[')[1].split(']')[0] for name in post.keys() if name.startswith(f'{prefix}[') and '][text]' in name
    }
    action_items = []

    for index in sorted(indices, key=int):
        text = post.get(f'{prefix}[{index}][text]', '').strip()
        threshold = post.get(f'{prefix}[{index}][threshold]', 3.0)
        stages = post.getlist(f'{prefix}[{index}][stages][]')
        key = post.get(f'{prefix}[{index}][key]', '').strip()

        if text:
            item = {'text': text, 'threshold': float(threshold)}

            if key in known_keys:
                item['key'] = key

            if stages:
                item['stages'] = [int(stage) for stage in stages]

            action_items.append(item)

    return add_action_item_keys(action_items)


def default_rating_labels(count, defaults):
    """The default labels of a score with count options: all five defaults, else only the two ends."""

    if count == len(defaults):
        return dict(defaults)

    return {'1': defaults['1'], f'{count}': defaults[f'{len(defaults)}']}


def rating_labels(stored, stored_count, posted, count, defaults):
    """The labels of a score after its number of options changed from stored_count to count.

    Labels the creator typed are kept for the values that remain. Default labels that nobody changed follow the new
    number, so a scale of 4 does not show "Agree" on its highest value.
    """

    posted = {key: label for key, label in posted.items() if label}

    if count != stored_count and stored == posted == default_rating_labels(stored_count, defaults):
        return default_rating_labels(count, defaults)

    return {key: label for key, label in posted.items() if key.isdigit() and 1 <= int(key) <= count}


def answer_counts(questionnaire):
    """The number of answers per question id, for the questions that have answers."""

    rows = (
        Response.objects.filter(question__section__questionnaire=questionnaire)
        .values('question')
        .annotate(count=Count('id'))
    )

    return {row['question']: row['count'] for row in rows}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _mapping(config):
    """The question's weights in the current format, {'skill': 1.5}, without the weights of 0.

    The older format names one model, {'dimension': 'skill', 'weight': 1.5}; a weight of the current format wins.
    """

    stored = config.get('dreyfus_mapping')
    if not isinstance(stored, dict):
        return {}

    mapping = {model: stored[model] for model in MODELS if model in stored}
    if stored.get('dimension') in MODELS and stored['dimension'] not in mapping:
        mapping[stored['dimension']] = stored.get('weight', 1)

    return {model: weight for model, weight in mapping.items() if _is_number(weight) and weight != 0}


def _apply_weight(config, model, weight):
    """Write the weight of the model into the config; a weight of 0 leaves no trace."""

    if model not in MODELS:
        raise EditorError(_('This model does not exist.'))

    if weight not in WEIGHTS:
        raise EditorError(_('This weight is not possible.'))

    mapping = _mapping(config)
    mapping.pop(model, None)

    if weight:
        mapping[model] = weight

    config.pop('dreyfus_mapping', None)

    if mapping:
        config['dreyfus_mapping'] = {model: mapping[model] for model in MODELS if model in mapping}


def set_weight(question, model, weight):
    """Store how much the question counts for the skill or initiative level."""

    _apply_weight(question.config, model, weight)
    question.save(update_fields=['config', 'updated_at'])


def _questions(questionnaire):
    return Question.objects.filter(section__questionnaire=questionnaire)


def clear_model(questionnaire, model):
    """Remove the weights of one model from every question of the questionnaire; the other model stays."""

    with transaction.atomic():
        for question in _questions(questionnaire):
            if 'dreyfus_mapping' in question.config:
                _apply_weight(question.config, model, 0)
                question.save(update_fields=['config', 'updated_at'])


def _offers_did_not_observe(question):
    """Without the key a score offers "Did not observe" and a likert does not."""

    return question.config.get('did_not_observe', question.question_type == 'rating')


def set_did_not_observe(questionnaire, on):
    """Offer "Did not observe" on every score and likert of the questionnaire, or on none."""

    with transaction.atomic():
        for question in _questions(questionnaire).filter(question_type__in=DID_NOT_OBSERVE_TYPES):
            question.config['did_not_observe'] = on
            question.save(update_fields=['config', 'updated_at'])


def did_not_observe_state(questionnaire):
    """'on' or 'off' when all scores and likerts agree, else 'mixed'. Without them 'on', the default of a score."""

    states = {
        bool(_offers_did_not_observe(question))
        for question in _questions(questionnaire).filter(question_type__in=DID_NOT_OBSERVE_TYPES)
    }

    if len(states) > 1:
        return 'mixed'

    return 'off' if states == {False} else 'on'


def _rating_count(post):
    try:
        count = int(post.get('rating_count', ''))
    except ValueError:
        count = None

    if count not in RATING_COUNTS:
        raise EditorError(_('A score has 2 to 7 options.'))

    return count


def _scale_config(post):
    try:
        config = {
            key: int(post.get(f'scale_{key}', default)) for key, default in (('min', 1), ('max', 100), ('step', 1))
        }
    except ValueError:
        raise EditorError(_('The lowest value, the highest value and the step of a slider must be whole numbers.'))

    if config['min'] >= config['max']:
        raise EditorError(_('The highest value of a slider must be more than its lowest value.'))

    if config['step'] <= 0:
        raise EditorError(_('The step of a slider must be more than 0.'))

    return config


def _drop_translations_above(question, count):
    """Remove the translated labels and descriptions of the values above count, and their checksums."""

    def kept(key):
        return not (key.isdigit() and int(key) > count)

    for row in question.translations.all():
        labels = {key: text for key, text in row.labels.items() if kept(key)}
        descriptions = {key: text for key, text in row.descriptions.items() if kept(key)}
        checksums = {
            key: checksum for key, checksum in row.source_checksums.items()
            if not key.startswith(('labels.', 'descriptions.')) or kept(key.split('.', 1)[1])
        }

        if (labels, descriptions, checksums) != (row.labels, row.descriptions, row.source_checksums):
            row.labels, row.descriptions, row.source_checksums = labels, descriptions, checksums
            row.save(update_fields=['labels', 'descriptions', 'source_checksums', 'updated_at'])


def save_question(questionnaire, post, question=None, section=None):
    """Store the posted question: a new one in section when question is None, else the changes to question.

    The config is built anew for the posted type, so the answers and settings of another type are dropped. The weights
    and chart settings stay unless weights are posted.
    """

    question_text = post.get('question_text', '').strip()
    question_type = post.get('question_type', '')

    if not question_text:
        raise EditorError(_('Write the question.'))

    if question_type not in dict(Question.QUESTION_TYPES):
        raise EditorError(_('Choose an answer type.'))

    default_likert_scale, defaults = get_default_labels(questionnaire)
    stored_config = question.config if question else {}
    config = {}
    labels = {}
    descriptions = {}
    option_rows = []

    if question_type == 'rating':
        count = _rating_count(post)
        stored_count = len(defaults)
        stored_labels = defaults

        if question and question.question_type == 'rating':
            stored_count = stored_config.get('max', len(defaults))
            stored_labels = question.labels

            if count != stored_count and question.responses.exists():
                raise EditorError(_('Reviewers already answered this question, so its number of options stays.'))

        posted = posted_labels(post, 'rating', count)
        labels = rating_labels(stored_labels, stored_count, posted, count, defaults)
        labels = labels or default_rating_labels(count, defaults)
        descriptions = posted_descriptions(post, 'rating', count)
        config = {'min': 1, 'max': count}
    elif question_type == 'likert':
        option_rows = posted_option_rows(post, 'likert') or [(None, label, None) for label in default_likert_scale]

        if post.get('reverse_scored') == 'on':
            config['reverse_scored'] = True
    elif question_type in ('single_choice', 'multiple_choice'):
        # Weights only count with scoring enabled; a weight that is not a number turns scoring off
        enable_scoring = post.get('enable_scoring') == 'on'

        try:
            option_rows = posted_option_rows(post, 'choice', with_weights=enable_scoring)
        except ValueError:
            option_rows = posted_option_rows(post, 'choice')
        else:
            if enable_scoring:
                config['scoring_enabled'] = True

        if question_type == 'single_choice' and post.get('display_list') != 'on':
            config['display'] = 'dropdown'
    elif question_type == 'scale':
        config = _scale_config(post)
        labels = posted_labels(post, 'scale')

    if question_type in DID_NOT_OBSERVE_TYPES:
        config['did_not_observe'] = post.get('did_not_observe') == 'on'

    for key in ('dreyfus_mapping', 'chart_weight', 'exclude_from_charts'):
        if key in stored_config:
            config[key] = stored_config[key]

    for model in MODELS:
        if f'{model}_weight' in post:
            try:
                weight = float(post[f'{model}_weight'])
            except ValueError:
                raise EditorError(_('This weight is not possible.'))

            _apply_weight(config, model, weight)

    try:
        action_items = posted_action_items(post, question)
    except ValueError:
        raise EditorError(_('The threshold and the stages of an advice item must be numbers.'))

    with transaction.atomic():
        if question is None:
            question = Question(section=section)
            order = section.questions.aggregate(Max('order'))['order__max']
            question.order = 0 if order is None else order + 1

        question.question_text = question_text
        question.question_type = question_type
        question.required = post.get('required') == 'on'
        question.config = config
        question.labels = labels
        question.descriptions = descriptions
        question.action_items = action_items
        question.save()
        save_options(question, option_rows)

        if question_type == 'rating':
            _drop_translations_above(question, config['max'])

    return question
