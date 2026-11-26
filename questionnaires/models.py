import uuid
from django.conf import settings
from django.db import models, transaction
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _, gettext
from core.models import TimeStampedModel, Organization
from core.managers import QuestionnaireManager
from .translations import Translatable


class Questionnaire(Translatable, TimeStampedModel):
    """Feedback questionnaire"""

    translated_fields = ['name', 'description']
    translated_children = 'sections'

    # Public UUID for external references (API, URLs)
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text=_('Public identifier for API and URL usage (non-enumerable)'),
        verbose_name=_('UUID')
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='questionnaires',
        null=True,  # Allow null for existing records and default questionnaires
        blank=True,
        verbose_name=_('organization')
    )
    name = models.CharField(_('name'), max_length=255)
    description = models.TextField(_('description'), blank=True)
    is_default = models.BooleanField(_('default'), default=False)
    is_active = models.BooleanField(_('active'), default=True)
    # The language of the texts above and of everything in the questionnaire; validated against settings.LANGUAGES
    # where it is set, so the language list is never frozen into a migration
    source_language = models.CharField(_('source language'), max_length=20, default=settings.LANGUAGE_CODE)
    # The shipped template the questionnaire was made from, see questionnaires/shipped.py
    template_key = models.CharField(_('template key'), max_length=50, blank=True)

    objects = QuestionnaireManager()

    class Meta:
        verbose_name = _('questionnaire')
        verbose_name_plural = _('questionnaires')
        db_table = 'questionnaires'
        ordering = ['-is_default', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # An organization has one default questionnaire. Templates (no organization) are all marked default,
        # so they are left alone.
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.is_default and self.organization_id:
                Questionnaire.objects.filter(organization_id=self.organization_id, is_default=True) \
                    .exclude(pk=self.pk).update(is_default=False)

    @property
    def dreyfus_dimensions(self):
        """Return (has_skill, has_agency) based on question dreyfus_mapping configs.

        A dimension counts as present if any question carries a non-zero weight
        for that dimension in its config['dreyfus_mapping']. Uses the prefetched
        sections/questions relation when available so it doesn't N+1 in list views.
        """
        has_skill = False
        has_agency = False

        for section in self.sections.all():
            for question in section.questions.all():
                mapping = (question.config or {}).get('dreyfus_mapping') or {}
                if not isinstance(mapping, dict):
                    continue
                try:
                    if mapping.get('skill') and float(mapping['skill']) != 0:
                        has_skill = True
                    if mapping.get('agency') and float(mapping['agency']) != 0:
                        has_agency = True
                except (TypeError, ValueError):
                    continue
                if has_skill and has_agency:
                    return has_skill, has_agency

        return has_skill, has_agency

    @property
    def report_type_label(self):
        """Human-readable description of what report this questionnaire produces."""
        has_skill, has_agency = self.dreyfus_dimensions
        if has_skill and has_agency:
            return gettext('Dreyfus (Skill + Agency)')
        if has_skill:
            return gettext('Dreyfus (Skill)')
        if has_agency:
            return gettext('Dreyfus (Agency)')
        return gettext('Standard 360')


class QuestionSection(Translatable, TimeStampedModel):
    """Section grouping questions within a questionnaire"""

    translated_fields = ['title', 'description']
    translated_children = 'questions'

    uuid = models.UUIDField(_('UUID'), default=uuid.uuid4, unique=True, editable=False)
    questionnaire = models.ForeignKey(
        Questionnaire,
        on_delete=models.CASCADE,
        related_name='sections',
        verbose_name=_('questionnaire')
    )
    title = models.CharField(_('title'), max_length=255)
    description = models.TextField(_('description'), blank=True)
    order = models.IntegerField(_('sort order'), default=0)

    class Meta:
        verbose_name = _('section')
        verbose_name_plural = _('sections')
        db_table = 'question_sections'
        ordering = ['questionnaire', 'order']
        unique_together = ['questionnaire', 'order']

    def __str__(self):
        return f"{self.questionnaire.name} - {self.title}"


class Question(Translatable, TimeStampedModel):
    """Individual question within a section"""

    translated_fields = ['question_text', 'labels', 'descriptions', 'action_items']
    translated_children = 'options'

    QUESTION_TYPES = [
        ('rating', _('Rating Scale')),
        ('likert', _('Likert Scale')),
        ('text', _('Free Text')),
        ('single_choice', _('Single Choice')),
        ('multiple_choice', _('Multiple Choice')),
        ('scale', _('Numeric Scale')),
    ]

    # Public UUID for external references (API, URLs)
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text=_('Public identifier for API and URL usage (non-enumerable)'),
        verbose_name=_('UUID')
    )

    section = models.ForeignKey(
        QuestionSection,
        on_delete=models.CASCADE,
        related_name='questions',
        verbose_name=_('section')
    )
    question_text = models.TextField(_('question text'))
    question_type = models.CharField(_('question type'), max_length=20, choices=QUESTION_TYPES)

    # JSON field for question configuration
    # For rating: {"min": 1, "max": 5}
    # For likert, single_choice and multiple_choice the options are AnswerOption rows
    # For single_choice and multiple_choice with scoring: {"scoring_enabled": true}, the options carry the weights
    #   Note: For multiple_choice, score = sum of selected option weights (rewards selecting more positive attributes)
    # For scale: {"min": 1, "max": 100, "step": 1}
    # Optional chart configuration:
    #   "chart_weight": 1.0 (default) - Weight in section average (0.5 = half weight, 2.0 = double weight)
    #   "exclude_from_charts": false (default) - Set true to exclude from chart aggregations
    # Optional Dreyfus model configuration:
    #   "dreyfus_mapping": {"skill": 1.5, "agency": 0.5} - Weights for skill/agency dimensions
    config = models.JSONField(_('configuration'), default=dict)

    # For rating: labels by value, {"1": "Poor", "5": "Excellent"}
    # For scale: labels of its ends, {"min": "Not at all", "max": "Extremely"}
    labels = models.JSONField(_('labels'), default=dict, blank=True)

    # For rating: what each value means, shown below the question on request, {"1": "Creates time pressure …"}
    descriptions = models.JSONField(_('descriptions'), default=dict, blank=True)

    # Personalized action items for development plans
    # Format: [
    #   {
    #     "key": "k3x9a2bq",  // Stable key a translation of the item refers to
    #     "text": "Practice pair programming with senior developers",
    #     "threshold": 3.0,  // Include if question score < threshold
    #     "stages": [1, 2, 3]  // Optional: Relevant Dreyfus stages (1-5)
    #   }
    # ]
    action_items = models.JSONField(_('action items'), default=list, blank=True)

    required = models.BooleanField(_('required'), default=True)
    order = models.IntegerField(_('sort order'), default=0)

    class Meta:
        verbose_name = _('question')
        verbose_name_plural = _('questions')
        db_table = 'questions'
        ordering = ['section', 'order']
        unique_together = ['section', 'order']

    def __str__(self):
        return f'{self.section.title} - {self.short_text}'

    @property
    def short_text(self):
        """The question text cut to 50 characters, for messages that quote it."""

        return Truncator(self.question_text).chars(50)

    @property
    def offers_did_not_observe(self):
        """Whether the reviewer may answer "Did not observe": only a score or a Likert question offers it.

        Without a setting a score offers it and a Likert does not, as before the setting existed.
        """

        if self.question_type not in ('rating', 'likert'):
            return False

        return bool((self.config or {}).get('did_not_observe', self.question_type == 'rating'))

    @property
    def options_data(self):
        """The answer options as plain data, for the editor and the export."""

        return [{'id': option.id, 'label': option.label, 'weight': option.weight} for option in self.options.all()]

    def get_source_value(self, field):
        """Action items are translated by their key."""

        if field == 'action_items':
            return {
                item['key']: item.get('text') for item in self.action_items if isinstance(item, dict) and 'key' in item
            }

        return super().get_source_value(field)

    def set_texts(self, texts):
        """Labels, descriptions and action items are translated by key; keys the source no longer has are left out."""

        labels = texts.get('labels', {})
        descriptions = texts.get('descriptions', {})
        action_items = texts.get('action_items', {})
        self.question_text = texts.get('question_text', self.question_text)
        self.labels = {key: labels.get(key, label) for key, label in self.labels.items()}
        self.descriptions = {key: descriptions.get(key, text) for key, text in self.descriptions.items()}
        self.action_items = [
            {**item, 'text': action_items.get(item.get('key'), item.get('text'))} if isinstance(item, dict) else item
            for item in self.action_items
        ]


class AnswerOption(Translatable, TimeStampedModel):
    """One selectable answer of a likert or choice question.

    Responses store the option's id, never its label, so a label can be reworded or translated without orphaning the
    answers already given.
    """

    translated_fields = ['label']

    question = models.ForeignKey(Question, models.CASCADE, 'options', verbose_name=_('question'))
    order = models.PositiveIntegerField(_('sort order'))
    label = models.CharField(_('label'), max_length=255)
    weight = models.FloatField(_('weight'), null=True, blank=True)

    class Meta:
        verbose_name = _('answer option')
        verbose_name_plural = _('answer options')
        db_table = 'answer_options'
        ordering = ['question', 'order']
        constraints = [
            models.UniqueConstraint(fields=['question', 'order'], name='answer_option_unique_order'),
        ]

    def __str__(self):
        return f'{self.question_id}: {self.label}'


class Translation(TimeStampedModel):
    """The texts of a questionnaire part in one language. An empty text is not translated yet."""

    # Validated against settings.LANGUAGES where it is set, so the language list is never frozen into a migration
    language = models.CharField(_('language'), max_length=20)
    # A checksum of the source text each text was translated from, by field; labels and action items by key, such as
    # "labels.5", so a changed source text shows its translation as outdated
    source_checksums = models.JSONField(_('source checksums'), default=dict, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.language


class QuestionnaireTranslation(Translation):
    """The name and description of a questionnaire in one language."""

    questionnaire = models.ForeignKey(Questionnaire, models.CASCADE, 'translations', verbose_name=_('questionnaire'))
    name = models.CharField(_('name'), max_length=255, blank=True)
    description = models.TextField(_('description'), blank=True)

    class Meta:
        verbose_name = _('questionnaire translation')
        verbose_name_plural = _('questionnaire translations')
        db_table = 'questionnaire_translations'
        constraints = [
            models.UniqueConstraint(fields=['questionnaire', 'language'], name='questionnaire_translation_unique'),
        ]


class QuestionSectionTranslation(Translation):
    """The title and description of a section in one language."""

    section = models.ForeignKey(QuestionSection, models.CASCADE, 'translations', verbose_name=_('section'))
    title = models.CharField(_('title'), max_length=255, blank=True)
    description = models.TextField(_('description'), blank=True)

    class Meta:
        verbose_name = _('section translation')
        verbose_name_plural = _('section translations')
        db_table = 'question_section_translations'
        constraints = [
            models.UniqueConstraint(fields=['section', 'language'], name='question_section_translation_unique'),
        ]


class QuestionTranslation(Translation):
    """The texts of a question in one language."""

    question = models.ForeignKey(Question, models.CASCADE, 'translations', verbose_name=_('question'))
    question_text = models.TextField(_('question text'), blank=True)
    # By the keys of Question.labels: {"1": "…", "5": "…"}
    labels = models.JSONField(_('labels'), default=dict, blank=True)
    # By the keys of Question.descriptions: {"1": "…", "5": "…"}
    descriptions = models.JSONField(_('descriptions'), default=dict, blank=True)
    # By the keys of Question.action_items: {"k3x9a2bq": "…"}
    action_items = models.JSONField(_('action items'), default=dict, blank=True)

    class Meta:
        verbose_name = _('question translation')
        verbose_name_plural = _('question translations')
        db_table = 'question_translations'
        constraints = [
            models.UniqueConstraint(fields=['question', 'language'], name='question_translation_unique'),
        ]


class AnswerOptionTranslation(Translation):
    """The label of an answer option in one language."""

    option = models.ForeignKey(AnswerOption, models.CASCADE, 'translations', verbose_name=_('answer option'))
    label = models.CharField(_('label'), max_length=255, blank=True)

    class Meta:
        verbose_name = _('answer option translation')
        verbose_name_plural = _('answer option translations')
        db_table = 'answer_option_translations'
        constraints = [
            models.UniqueConstraint(fields=['option', 'language'], name='answer_option_translation_unique'),
        ]
