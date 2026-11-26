"""
The save logic of the questionnaire editor.

The editor page posts the fields of one question, or one weight, and shows the result. These functions check what was
posted and store it. Their EditorError texts are shown to the creator. report_preview computes the example report the
page shows next to the questions.
"""

import random
from functools import partial
from math import isfinite

from django.db import transaction
from django.db.models import Count, Max
from django.utils import translation
from django.utils.translation import gettext as _, gettext_lazy

from core.languages import is_language, language_name
from reports.dreyfus_service import _level_to_stage, agency_profile_with_texts, skill_profile_with_texts
from reports.scoring import score_range
from reports.services import radar_axes
from reviews.models import Response

from .action_items import add_action_item_keys
from .answer_options import DEFAULT_LIKERT_SCALE, DEFAULT_RATING_LABELS, OPTION_TYPES, save_options
from .models import AnswerOption, Question, QuestionSection, Questionnaire
from .presentation import question_scoring
from .translations import get_language_states, has_translation

WEIGHTS = (0, 0.5, 1, 1.5, 2)
WEIGHT_NAMES = {
    0: gettext_lazy('Does not count'),
    0.5: gettext_lazy('Counts half'),
    1: gettext_lazy('Counts once'),
    1.5: gettext_lazy('Counts 1.5 times'),
    2: gettext_lazy('Counts double'),
}
MODELS = ('skill', 'agency')
# The texts of each model in the card "The report" and in the report preview; a new model of MODELS needs its entry
MODEL_TEXTS = {
    'skill': {
        'choice': gettext_lazy('Skill level (Dreyfus model)'),
        'help': gettext_lazy('Shows which of five stages the person is at, from Novice to Expert.'),
        'name': gettext_lazy('Skill level'),
        'example': gettext_lazy('Example: "Alex solves hard problems without help" says something about skill.'),
    },
    'agency': {
        'choice': gettext_lazy('Initiative (agency model)'),
        'help': gettext_lazy('Shows how much the person acts without being asked, in five levels.'),
        'name': gettext_lazy('Initiative'),
        'example': gettext_lazy(
            'Example: "Alex starts improvements without being asked" says something about initiative.'
        ),
    },
}

# The example scores of the reviewer groups in the report preview, as shifts of a topic's example score
EXAMPLE_GROUP_SHIFTS = {'self': -0.2, 'peer': 0, 'manager': 0.2, 'direct_report': 0.1}
EXAMPLE_CASES = {0: 'none', 1: 'bars', 2: 'overall'}
PROFILES = {'skill': skill_profile_with_texts, 'agency': agency_profile_with_texts}

# The names of the answer types on the editor page
ANSWER_TYPES = {
    'rating': gettext_lazy('Score'),
    'likert': gettext_lazy('Agree / disagree (Likert)'),
    'text': gettext_lazy('Written answer'),
    'single_choice': gettext_lazy('Pick one'),
    'multiple_choice': gettext_lazy('Pick several'),
    'scale': gettext_lazy('Slider'),
}

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
    number, so a scale of 4 does not show "Agree" on its highest value. The form may post the fields of the old or of
    the new number of options, so the stored labels decide: they are the default, and no posted field (empty ones
    included) differs from them.
    """

    unchanged = all(label == stored.get(key, '') for key, label in posted.items())

    if count != stored_count and unchanged and stored == default_rating_labels(stored_count, defaults):
        return default_rating_labels(count, defaults)

    return {key: label for key, label in posted.items() if label and key.isdigit() and 1 <= int(key) <= count}


def _translation_languages(question, options=True):
    """The codes of the languages with a translated label or description of the question, or of one of its answers."""

    languages = {
        row.language for row in question.translations.all()
        if any(row.labels.values()) or any(row.descriptions.values())
    }

    if options:
        languages.update(
            row.language for option in question.options.all() for row in option.translations.all() if row.label
        )

    return languages


def translated_into(question):
    """The names of the languages that have a translation of the question's labels, descriptions or answers: the
    texts a change of the answer type removes. Uses the prefetched translations."""

    if question.pk is None:
        return []

    return sorted(language_name(language) for language in _translation_languages(question))


def _on_five(value, low, high):
    """value on the report's 1 to 5 scale, as reports.scoring.score_on_five() computes it."""

    return round(1 + (value - low) / (high - low) * 4, 1)


def question_form_values(questionnaire, question):
    """The values the open question shows that its stored fields do not hold as such.

    Each answer type has its fields in the form, also the types the question does not have, so a switch to another
    type and back keeps what was typed. A type the question does not have shows what a new question of that type
    starts with. Gives the rows of a score with what each counts as on the report's 1 to 5 scale, a description field
    for each possible value, the answers of a likert and of a pick question, the slider, the weight per model, the
    lowest and highest score of a slider or a pick several, and the languages of translated labels and descriptions.
    """

    default_likert_scale, default_labels = get_default_labels(questionnaire)
    question_type = question.question_type
    options = question.options_data if question.pk and question_type in OPTION_TYPES else []
    count = len(default_labels)
    labels = default_labels

    if question_type == 'rating':
        stored_max = question.config.get('max')
        # As the reviewer form reads it: a max that is not a whole number from 2 to 7 gives five options
        if isinstance(stored_max, int) and not isinstance(stored_max, bool) and stored_max in RATING_COUNTS:
            count = stored_max
        labels = question.labels

    choices = options if question_type in ('single_choice', 'multiple_choice') else []
    scale = question.config if question_type == 'scale' else {}
    bounds = score_range({'question_type': question_type, 'question_config': question.config, 'options': options})

    return {
        'rating_rows': [
            {'value': value, 'label': labels.get(f'{value}', ''), 'counts_as': _on_five(value, 1, count)}
            for value in range(1, count + 1)
        ],
        'rating_count': count,
        'descriptions': [
            {'value': value, 'text': question.descriptions.get(f'{value}', '')}
            for value in range(1, RATING_COUNTS[-1] + 1)
        ],
        'likert_options': options if question_type == 'likert' else [
            {'id': '', 'label': f'{label}'} for label in default_likert_scale
        ],
        # A choice without scores shows the position as the score to start from
        'choice_options': [
            {**option, 'weight': option['weight'] if option['weight'] is not None else position}
            for position, option in enumerate(choices, 1)
        ] or [{'id': '', 'label': '', 'weight': position} for position in range(1, 4)],
        'scale': {
            'min': scale.get('min', 1), 'max': scale.get('max', 10), 'step': scale.get('step', 1),
            'min_label': question.labels.get('min', '') if scale else '',
            'max_label': question.labels.get('max', '') if scale else '',
        },
        'rating_counts': RATING_COUNTS,
        'weights': [{'model': model, 'weight': _mapping(question.config).get(model, 0)} for model in MODELS],
        'weight_names': WEIGHT_NAMES,
        'range': bounds,
        'label_languages': sorted(
            language_name(language) for language in _translation_languages(question, options=False)
        ) if question.pk else [],
    }


def languages_with_translation(question):
    """The names of the languages that have any translation of the question: its text, labels, descriptions, advice
    or answers. Uses the prefetched translations."""

    if question.pk is None:
        return []

    languages = _translation_languages(question)
    languages.update(
        row.language for row in question.translations.all()
        if row.question_text or any(row.action_items.values())
    )

    return sorted(language_name(language) for language in languages)


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

    # Also refused when no question has a weight, which _apply_weight alone would not notice
    if model not in MODELS:
        raise EditorError(_('This model does not exist.'))

    with transaction.atomic():
        for question in _questions(questionnaire):
            if 'dreyfus_mapping' in question.config:
                _apply_weight(question.config, model, 0)
                question.save(update_fields=['config', 'updated_at'])


def set_did_not_observe(questionnaire, on):
    """Offer "Did not observe" on every score and likert of the questionnaire, or on none."""

    with transaction.atomic():
        for question in _questions(questionnaire).filter(question_type__in=DID_NOT_OBSERVE_TYPES):
            question.config['did_not_observe'] = on
            question.save(update_fields=['config', 'updated_at'])


def did_not_observe_state(questionnaire):
    """'on' or 'off' when all scores and likerts agree, else 'mixed'. Without them 'on', the default of a score."""

    states = {
        question.offers_did_not_observe
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
    and chart settings stay unless weights are posted. The action items change only when the post has the marker
    action_items_posted, which the form sends with the advice fields; a form that does not show them keeps them.
    """

    question_text = post.get('question_text', '').strip()
    question_type = post.get('question_type', '')

    if not question_text:
        raise EditorError(_('Write the question.'))

    if question_type not in dict(Question.QUESTION_TYPES):
        raise EditorError(_('Choose an answer type.'))

    # Old answers of another type would be read as numbers, such as the id of an answer option as a score
    answered = question is not None and question.responses.exists()

    if answered and question_type in ('rating', 'scale') and question_type != question.question_type:
        raise EditorError(
            _('Reviewers already answered this question as another type. Add a new question for a score or a slider.')
        )

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

            if count != stored_count and answered:
                raise EditorError(_('Reviewers already answered this question, so its number of options stays.'))

        # Every posted field counts, also an empty one, up to the higher of the two numbers
        fields = {f'{value}': f'rating_label_{value}' for value in range(1, max(count, stored_count) + 1)}
        posted = {key: post[field].strip() for key, field in fields.items() if field in post}

        if question is None and not any(name.startswith('rating_label_') for name in post):
            labels = default_rating_labels(count, defaults)
        else:
            labels = rating_labels(stored_labels, stored_count, posted, count, defaults)

        descriptions = posted_descriptions(post, 'rating', count)
        config = {'min': 1, 'max': count}
    elif question_type == 'likert':
        option_rows = posted_option_rows(post, 'likert')

        # A stored likert would lose its answers and their translations; a new one starts with the default scale
        if not option_rows and question is not None:
            raise EditorError(_('A question of this type needs answers. Add at least two.'))

        option_rows = option_rows or [(None, label, None) for label in default_likert_scale]

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

    label_length = AnswerOption._meta.get_field('label').max_length

    if any(len(label) > label_length for option_id, label, weight in option_rows):
        raise EditorError(_('This text is too long. Use at most %(count)s characters.') % {'count': label_length})

    if post.get('action_items_posted'):
        try:
            action_items = posted_action_items(post, question)
        except ValueError:
            raise EditorError(_('The threshold and the stages of an advice item must be numbers.'))
    else:
        action_items = question.action_items if question else []

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


def example_score(question):
    """The example score of a question in the editor's report preview.

    It depends on the question id alone, so the numbers do not change while the creator types.
    """

    return round(random.Random(question.id).uniform(3.0, 4.6), 1)


def _example_level(model, rows):
    """The level of one model made from rows of {'question', 'score', 'weight', 'weight_name'}, as the report shows
    it."""

    weight_sum = sum(row['weight'] for row in rows)
    level = stage = low = high = profile = None

    if rows:
        level = round(sum(row['score'] * row['weight'] for row in rows) / weight_sum, 2)
        stage = _level_to_stage(level)
        low, high = max(1, stage - 0.5), min(5, stage + 0.5)
        # The same profile the sample report builds
        profile = PROFILES[model]({f'{model}_level': level, 'stage': stage, 'confidence': 0.85})

    return {
        'model': model,
        'rows': rows,
        'weight_sum': weight_sum,
        'level': level,
        'stage': stage,
        'low': low,
        'high': high,
        'profile': profile,
    }


def report_preview(questionnaire, shown):
    """The example report the editor shows next to the questions: the topics that are a point on the radar, the
    example scores of the chart, and how each level that is on is made from the questions that count.

    A model is on when it is in shown (ticked in this visit) or a question has a weight for it, in either format. Uses the prefetched
    sections, questions and options.
    """

    on = set(shown)
    rows = {model: [] for model in MODELS}
    topics = []
    section_scores = {}

    for section in questionnaire.sections.all():
        questions = list(section.questions.all())
        radar_scores = []

        for question in questions:
            scoring = question_scoring(question)

            if scoring.in_radar:
                radar_scores.append(example_score(question))

            # A weight turns its model on, in both formats, also on a question that cannot count
            mapping = _mapping(question.config) if isinstance(question.config, dict) else {}
            on.update(mapping)

            if scoring.nonzero:
                for model, weight in mapping.items():
                    rows[model].append({
                        'question': question, 'score': example_score(question), 'weight': weight,
                        # An older weight outside the five shows as its number
                        'weight_name': WEIGHT_NAMES.get(weight, weight),
                    })

        topics.append({
            'id': section.id,
            'title': section.title,
            'questions': len(questions),
            'counting': len(radar_scores),
            'point': bool(radar_scores),
        })

        if radar_scores:
            mean = sum(radar_scores) / len(radar_scores)
            section_scores[section.title] = {
                group: round(min(5, max(1, mean + shift)), 2) for group, shift in EXAMPLE_GROUP_SHIFTS.items()
            }

    axes = radar_axes(section_scores)
    case = EXAMPLE_CASES.get(len(section_scores), 'radar')

    # Two points without a radar: a topic is titled like the added point, so the report draws bars
    if axes is None and section_scores:
        case = 'bars'

    # Like the report, the chart is keyed by title, so two topics with one title are one point
    return {
        'topics': topics,
        'case': case,
        'chart': {'section_scores': section_scores},
        'radar_axes': axes,
        'levels': [_example_level(model, rows[model]) for model in MODELS if model in on],
    }


def _text(value, field, required_message):
    """The posted text for a model field, stripped; refused when it is required and empty, or too long."""

    text = (value or '').strip()

    if required_message and not text:
        raise EditorError(required_message)

    if field.max_length and len(text) > field.max_length:
        raise EditorError(_('This text is too long. Use at most %(count)s characters.') % {'count': field.max_length})

    return text


def save_info(questionnaire, post):
    """Store the name, description, original language and default flag the settings of the editor posted."""

    source_language = post.get('source_language', '')

    if not is_language(source_language):
        raise EditorError(_('Choose a language.'))

    # The original language cannot also have a translation
    if source_language != questionnaire.source_language and has_translation(questionnaire, source_language):
        raise EditorError(
            _('This questionnaire is already translated into %(language)s. Empty that translation first to make '
              '%(language)s its original language.') % {'language': language_name(source_language)}
        )

    questionnaire.name = _text(post.get('name'), Questionnaire._meta.get_field('name'), _('Write a name.'))
    questionnaire.description = post.get('description', '').strip()
    questionnaire.source_language = source_language
    questionnaire.is_default = bool(post.get('is_default'))
    questionnaire.save()


def add_section(questionnaire):
    """Add a topic at the end of the questionnaire, titled "New topic" in the questionnaire's original language."""

    order = questionnaire.sections.aggregate(Max('order'))['order__max']

    with translation.override(questionnaire.source_language):
        title = _('New topic')

    return QuestionSection.objects.create(
        questionnaire=questionnaire, title=title, order=0 if order is None else order + 1,
    )


def save_section(section, title, description):
    """Store the title and description of a topic; a topic needs a title."""

    section.title = _text(title, QuestionSection._meta.get_field('title'), _('A topic needs a title.'))
    section.description = (description or '').strip()
    section.save(update_fields=['title', 'description', 'updated_at'])


def load_for_editor(questionnaire):
    """The questionnaire loaded anew, with its sections, questions, options and their translations prefetched."""

    return Questionnaire.objects.prefetch_related(*Questionnaire.translation_lookups()).get(pk=questionnaire.pk)


def editor_context(questionnaire, shown, topic=None):
    """The context of the editor page and of each of its slots.

    questionnaire comes from load_for_editor(). shown holds the report models ticked in this visit. topic is the id of
    the section the reviewer tab shows, by default the first. Each section gets its entry of the report preview's
    topics and the number of answers to its questions, each question its Scoring and its number of answers. The card
    "The report" gets each model of MODELS and the table of the questions with a score. The language states and the
    state of "Did not observe" are computed only when a slot shows them.
    """

    preview = report_preview(questionnaire, shown)
    topics = {entry['id']: entry for entry in preview['topics']}
    answers = answer_counts(questionnaire)
    sections = list(questionnaire.sections.all())
    levels = {level['model']: level for level in preview['levels']}
    weighted = dict.fromkeys(MODELS, 0)
    weight_table = []

    for section in sections:
        section.editor_topic = topics[section.id]
        section.answer_count = 0
        scored = []

        for question in section.questions.all():
            question.scoring = question_scoring(question)
            question.answer_count = answers.get(question.id, 0)
            section.answer_count += question.answer_count
            mapping = _mapping(question.config) if isinstance(question.config, dict) else {}

            for model in mapping:
                weighted[model] += 1

            if question.scoring.has_score:
                scored.append({
                    'question': question,
                    'weights': [
                        {'model': model, 'name': MODEL_TEXTS[model]['name'], 'weight': mapping.get(model, 0)}
                        for model in levels
                    ],
                })

        if scored:
            weight_table.append({'title': section.title, 'questions': scored})

    reviewer_section = next((section for section in sections if f'{section.id}' == f'{topic}'), None)

    return {
        'questionnaire': questionnaire,
        'sections': sections,
        'preview': preview,
        'models_on': list(levels),
        # Per model: its texts, whether it is on, how many questions have a weight for it, and its example level
        'report_models': [
            {'model': model, **MODEL_TEXTS[model], 'weighted': weighted[model], 'level': levels.get(model)}
            for model in MODELS
        ],
        # The questions with a score, per topic, with their weight for each model that is on
        'weight_table': weight_table,
        'weight_names': WEIGHT_NAMES,
        'answer_types': ANSWER_TYPES,
        'reviewer_section': reviewer_section or (sections[0] if sections else None),
        'source_language_name': language_name(questionnaire.source_language),
        'language_states': partial(get_language_states, questionnaire),
        'did_not_observe': partial(did_not_observe_state, questionnaire),
        'chart': {'data': preview['chart'], 'axes': preview['radar_axes']},
    }
