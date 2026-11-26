"""
Translations of questionnaires.

The text fields of a questionnaire, its sections, questions and answer options hold the questionnaire's source language.
Their translations live in one table per model, with one row per language. A text left empty there is not translated,
and the source text is shown instead.
"""

import copy
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby
from operator import attrgetter

from django.conf import settings
from django.db import transaction
from django.db.models import prefetch_related_objects
from django.utils.translation import get_language, gettext, gettext_lazy as _, pgettext_lazy

from core.languages import get_base_language, is_language, language_name, translation_languages

# A checksum only has to tell one version of a source text from the next
CHECKSUM_LENGTH = 16

# Source texts that the translation page edits in a text area instead of a single line
MULTILINE_FIELDS = ['description', 'question_text', 'descriptions', 'action_items']

# What a text is, by the model name of its part and its field
TEXT_LABELS = {
    ('questionnaire', 'name'): _('Name'),
    ('questionnaire', 'description'): _('Description'),
    ('questionsection', 'title'): _('Topic title'),
    ('questionsection', 'description'): _('Topic description'),
    ('question', 'question_text'): _('Question'),
    # The words of the editor: the same msgids as its templates
    ('question', 'action_items'): _('Advice'),
    ('answeroption', 'label'): pgettext_lazy('noun', 'Answer'),
}
SCALE_LABELS = {
    'min': _('Label of the lowest value'),
    'max': _('Label of the highest value'),
}


def get_checksum(text):
    """A checksum of a source text, kept with its translation to notice when the source text changes."""

    return hashlib.sha256(text.encode()).hexdigest()[:CHECKSUM_LENGTH]


def get_text_key(field, item):
    """The key of a text among the source checksums: the field, or field.item such as labels.5."""

    return f'{field}.{item}' if item else field


def flatten_texts(values):
    """
    The texts of the fields in values by (field, item): item is the key of a text that the field holds by key, such as
    the 5 of a rating label, and empty for the field's own text. Empty texts are left out.
    """

    texts = {}

    for field, value in values.items():
        if isinstance(value, dict):
            texts.update({(field, item): text for item, text in value.items()})
        else:
            texts[field, ''] = value

    return {key: text for key, text in texts.items() if text}


def set_prefetched(instance, relation, objects):
    """
    Make instance.<relation>.all() return objects instead of the rows in the database.

    This fills Django's prefetch cache, which is not public API; test_translations.py notices when that changes.
    """

    queryset = getattr(instance, relation).all()._chain()
    queryset._result_cache = list(objects)
    queryset._prefetch_done = True
    instance._prefetched_objects_cache = {**instance._prefetched_objects_cache, relation: queryset}


def copy_translations(translations, parent):
    """Save copies of translations for parent, a copy of the object they were made for."""

    relation = parent.translations
    copies = list(translations)

    for translation in copies:
        translation.pk = None
        setattr(translation, relation.field.name, parent)

    relation.model.objects.bulk_create(copies)


class Translatable:
    """
    A model whose texts can be translated.

    translated() returns a copy in another language. The copy shares the primary key of the original, so it refuses to
    be saved: that would store the translation as the source text.
    """

    # The text fields that the model's translations hold
    translated_fields = []
    # The related name of the children translated along with the object
    translated_children = None
    # The language of a translated copy
    translated_into = None

    def save(self, *args, **kwargs):
        if self.translated_into:
            raise ValueError(f'A copy translated into {self.translated_into} cannot be saved')

        super().save(*args, **kwargs)

    @classmethod
    def translation_lookups(cls):
        """The lookups that prefetch the translations of an object and of all its descendants."""

        lookups = ['translations']

        if cls.translated_children:
            child_model = cls._meta.get_field(cls.translated_children).related_model
            lookups.extend(f'{cls.translated_children}__{lookup}' for lookup in child_model.translation_lookups())

        return lookups

    def get_translated_texts(self, language):
        """The texts translated into language, by field. Fields holding texts by key give only the translated keys."""

        translations = {translation.language: translation for translation in self.translations.all()}
        texts = {}

        # The base language first, so the texts of a variant win
        for code in reversed(translation_languages(language)):
            if translation := translations.get(code):
                for field in self.translated_fields:
                    value = getattr(translation, field)

                    if isinstance(value, dict):
                        texts[field] = {**texts.get(field, {}), **{key: text for key, text in value.items() if text}}
                    elif value:
                        texts[field] = value

        return texts

    def set_texts(self, texts):
        """Put the translated texts into the fields of this copy."""

        for field, text in texts.items():
            setattr(self, field, text)

    def translated(self, language=None):
        """
        A copy in language, by default the active one, with its children translated as well. Untranslated texts stay in
        the source language.
        """

        language = language or get_language()
        prefetch_related_objects([self], *self.translation_lookups())

        translation = copy.copy(self)
        translation.translated_into = language
        translation.set_texts(self.get_translated_texts(language))

        if self.translated_children:
            children = getattr(self, self.translated_children).all()
            set_prefetched(translation, self.translated_children, [child.translated(language) for child in children])

        return translation

    def get_source_value(self, field):
        """The source text of a field, or the texts it holds by key."""

        return getattr(self, field)

    def get_source_texts(self):
        """The source texts that translations translate, by (field, item), see flatten_texts()."""

        return flatten_texts({field: self.get_source_value(field) for field in self.translated_fields})


@dataclass
class TextTranslation:
    """A source text of a questionnaire part and where its translation into one language stands."""

    part: Translatable
    # The section the part belongs to, None for the questionnaire itself
    section: Translatable | None
    field: str
    # The key of a text that the field holds by key, empty for the field's own text
    item: str
    source: str
    # The translation into exactly this language; empty if there is none
    text: str
    # The translation into the base language, which a variant shows while its own text is empty
    fallback: str
    # Whether the text shows in the source language, although that is another language
    missing: bool
    # Whether the source text changed since the translation that shows was made
    outdated: bool

    @property
    def key(self):
        return get_text_key(self.field, self.item)

    @property
    def field_name(self):
        """The name of the text's input on the translation page."""

        return f'{self.part._meta.model_name}-{self.part.id}-{self.key}'

    @property
    def label(self):
        """What the text is, for the translation page."""

        if self.field == 'descriptions':
            return gettext('Description of rating %(value)s') % {'value': self.item}

        if self.field != 'labels':
            return TEXT_LABELS[self.part._meta.model_name, self.field]

        return SCALE_LABELS.get(self.item) or gettext('Label of rating %(value)s') % {'value': self.item}

    @property
    def multiline(self):
        return self.field in MULTILINE_FIELDS

    @property
    def max_length(self):
        """The most characters the translation may have, None for no limit."""

        return self.part.translations.model._meta.get_field(self.field).max_length


@dataclass
class LanguageState:
    """How far a questionnaire is translated into one language."""

    code: str
    name: str
    # The texts that show in this language, translated or through the base language of a variant
    translated: int
    missing: int
    outdated: int

    @classmethod
    def from_texts(cls, language, texts):
        """The state of the translation into language, from its TextTranslations."""

        return cls(
            code=language,
            name=language_name(language),
            translated=sum(bool(text.text or text.fallback) for text in texts),
            missing=sum(text.missing for text in texts),
            outdated=sum(text.outdated for text in texts),
        )


def get_parts(questionnaire):
    """The questionnaire, its sections, questions and options, each with its section, in the order of the editor."""

    prefetch_related_objects([questionnaire], *questionnaire.translation_lookups())
    parts = [(None, questionnaire)]

    for section in questionnaire.sections.all():
        parts.append((section, section))

        for question in section.questions.all():
            parts.append((section, question))
            parts.extend((section, option) for option in question.options.all())

    return parts


def get_text_translations(questionnaire, language):
    """Every source text of the questionnaire with where its translation into language stands, in editor order."""

    languages = translation_languages(language)
    # A variant of the source language shows the source text where it has no text of its own
    needs_translation = get_base_language(language) != get_base_language(questionnaire.source_language)
    texts = []

    for section, part in get_parts(questionnaire):
        translations = {translation.language: translation for translation in part.translations.all()}
        translated_texts = defaultdict(dict, {
            code: flatten_texts({field: getattr(translation, field) for field in part.translated_fields})
            for code, translation in translations.items()
        })

        for (field, item), source in part.get_source_texts().items():
            # The most specific language with a text of its own, whose text shows
            showing = next((code for code in languages if translated_texts[code].get((field, item))), None)
            fallbacks = [translated_texts[code].get((field, item)) for code in languages[1:]]
            checksum = translations[showing].source_checksums.get(get_text_key(field, item)) if showing else None
            texts.append(TextTranslation(
                part=part,
                section=section,
                field=field,
                item=item,
                source=source,
                text=translated_texts[language].get((field, item), ''),
                fallback=next(filter(None, fallbacks), ''),
                missing=not showing and needs_translation,
                outdated=bool(showing) and checksum != get_checksum(source),
            ))

    return texts


def get_language_states(questionnaire):
    """How far the questionnaire is translated into each language other than its source language."""

    return [
        LanguageState.from_texts(code, get_text_translations(questionnaire, code))
        for code, name in settings.LANGUAGES
        if code != questionnaire.source_language
    ]


def has_translation(questionnaire, language):
    """Whether any text of the questionnaire is translated into exactly this language."""

    return any(text.text for text in get_text_translations(questionnaire, language))


def save_part_translation(part, language, texts, data):
    """Store the posted translations of one part's texts, see save_text_translations()."""

    relation = part.translations
    translation = next((row for row in relation.all() if row.language == language), None)

    if translation is None:
        translation = relation.model(**{relation.field.name: part, 'language': language})

    values = {field: {} if isinstance(getattr(translation, field), dict) else '' for field in part.translated_fields}
    checksums = {}

    for text in texts:
        posted = data.get(text.field_name, '').strip()

        if not posted:
            continue

        if text.item:
            values[text.field][text.item] = posted
        else:
            values[text.field] = posted

        if posted != text.text or data.get(f'current-{text.field_name}'):
            checksums[text.key] = get_checksum(text.source)
        elif checksum := translation.source_checksums.get(text.key):
            checksums[text.key] = checksum

    if not any(values.values()):
        if translation.pk:
            translation.delete()

        return

    for field, value in values.items():
        setattr(translation, field, value)

    translation.source_checksums = checksums
    translation.save()


def get_length_errors(texts, data):
    """The errors for the posted translations in data that are longer than their texts allow."""

    return [
        gettext('The translation of "%(text)s" is longer than %(max_length)s characters.') % {
            'text': text.source,
            'max_length': text.max_length,
        }
        for text in texts
        if text.max_length and len(data.get(text.field_name, '').strip()) > text.max_length
    ]


def save_text_translations(questionnaire, language, data):
    """
    Store the translations posted on the translation page; returns the errors, and stores nothing if there are any.

    An empty text removes its translation. A changed text, and an outdated one confirmed as still correct, get the
    checksum of their source text. Translations of texts the source no longer has are dropped.
    """

    texts = get_text_translations(questionnaire, language)

    if errors := get_length_errors(texts, data):
        return errors

    with transaction.atomic():
        for part, part_texts in groupby(texts, key=attrgetter('part')):
            save_part_translation(part, language, list(part_texts), data)

    return []


def save_one_translation(questionnaire, language, field_name, value, still_correct=False):
    """
    Store the translation of the text with field_name, as save_text_translations() does for all texts; returns the
    errors, and stores nothing if there are any. The other texts of the same part keep their translations and checksums.
    """

    texts = get_text_translations(questionnaire, language)
    text = next((text for text in texts if text.field_name == field_name), None)

    if text is None:
        return [gettext('The questionnaire has no text to translate here.')]

    # save_part_translation() stores the part's texts from data alone, so data holds the stored ones as well
    part_texts = [other for other in texts if other.part == text.part]
    data = {other.field_name: other.text for other in part_texts}
    data[field_name] = value

    if still_correct:
        data[f'current-{field_name}'] = 'on'

    if errors := get_length_errors([text], data):
        return errors

    save_part_translation(text.part, language, part_texts, data)

    return []


def get_translations_data(part):
    """The translations of a questionnaire part as plain data for the export, by language."""

    return {
        translation.language: {
            **{field: getattr(translation, field) for field in part.translated_fields},
            'source_checksums': translation.source_checksums,
        }
        for translation in part.translations.all()
    }


def import_translations(part, data, source_language):
    """
    Create the translations of a questionnaire part from exported data. Languages this install does not offer, the
    source language and values of the wrong type are left out.
    """

    if not isinstance(data, dict):
        return

    relation = part.translations
    translations = []

    for language, values in data.items():
        if not is_language(language) or language == source_language or not isinstance(values, dict):
            continue

        translation = relation.model(**{relation.field.name: part, 'language': language})

        for field in [*part.translated_fields, 'source_checksums']:
            value = values.get(field)

            if isinstance(getattr(translation, field), dict):
                texts = value if isinstance(value, dict) else {}
                value = {f'{key}': text for key, text in texts.items() if isinstance(text, str)}
            elif not isinstance(value, str):
                value = ''

            setattr(translation, field, value)

        translations.append(translation)

    relation.model.objects.bulk_create(translations)

