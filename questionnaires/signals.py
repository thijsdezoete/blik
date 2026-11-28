from django.db.models.signals import post_save
from django.db.backends.signals import connection_created
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.core.management import call_command
from core.models import Organization
from .legacy_config import move_all_texts_out_of_config
from .models import AnswerOption, Questionnaire, QuestionSection, Question
from .shipped import add_shipped_translations
from .translations import copy_translations
import logging
import uuid

logger = logging.getLogger(__name__)


def copy_of(instance, **values):
    """An unsaved copy of instance. values replace those of the original, by column name."""

    fields = [field for field in instance._meta.concrete_fields if not field.primary_key]

    return type(instance)(**{field.attname: getattr(instance, field.attname) for field in fields} | values)


def clone_translations(originals, clones):
    """Save copies of the translations of each original for its clone, in one insert."""

    if not clones:
        return

    relation = clones[0].translations
    relation.model.objects.bulk_create(
        copy_of(translation, **{relation.field.attname: clone.pk})
        for original, clone in zip(originals, clones)
        for translation in original.translations.all()
    )


def clone_questionnaire_for_organization(questionnaire, organization):
    """
    Clone a template questionnaire with all sections and questions for a specific organization.

    Args:
        questionnaire: The template questionnaire to clone (should have organization=None)
        organization: The organization to clone the questionnaire for

    Returns:
        The cloned questionnaire instance
    """
    cloned_questionnaire = Questionnaire.objects.create(
        organization=organization,
        name=questionnaire.name,
        description=questionnaire.description,
        is_default=False,  # Only templates should be marked as default
        is_active=questionnaire.is_active,
        source_language=questionnaire.source_language,
        template_key=questionnaire.template_key,
    )
    copy_translations(questionnaire.translations.all(), cloned_questionnaire)

    # A new organization gets every template, so a query per question adds up. Read the whole questionnaire first,
    # then write each level in one insert.
    sections = list(
        QuestionSection.objects.filter(questionnaire=questionnaire).order_by('order')
        .prefetch_related('translations', 'questions__translations', 'questions__options__translations')
    )
    questions = [question for section in sections for question in section.questions.all()]
    options = [option for question in questions for option in question.options.all()]

    cloned_sections = QuestionSection.objects.bulk_create(
        copy_of(section, questionnaire_id=cloned_questionnaire.pk, uuid=uuid.uuid4()) for section in sections
    )
    section_ids = {section.pk: clone.pk for section, clone in zip(sections, cloned_sections)}
    cloned_questions = Question.objects.bulk_create(
        copy_of(question, section_id=section_ids[question.section_id], uuid=uuid.uuid4()) for question in questions
    )
    question_ids = {question.pk: clone.pk for question, clone in zip(questions, cloned_questions)}
    cloned_options = AnswerOption.objects.bulk_create(
        copy_of(option, question_id=question_ids[option.question_id]) for option in options
    )

    clone_translations(sections, cloned_sections)
    clone_translations(questions, cloned_questions)
    clone_translations(options, cloned_options)

    return cloned_questionnaire


@receiver(post_migrate)
def load_default_questionnaire_fixtures(sender, **kwargs):
    """
    Automatically load default questionnaire fixtures after migrations.

    This ensures that template questionnaires are available even after a database reset.
    Only loads if no template questionnaires exist.
    """
    # Only run for the questionnaires app
    if sender.name != 'questionnaires':
        return

    # Check if any template questionnaires exist
    if Questionnaire.objects.templates().exists():
        logger.info("Template questionnaires already exist, skipping fixture load")
        return

    # Load the default questionnaire fixtures
    fixtures = [
        'professional_skills_questionnaire',
        'software_engineering_questionnaire',
        'manager_360_questionnaire',
        'simple_questionnaire',
    ]

    logger.info("Loading default questionnaire fixtures...")
    for fixture in fixtures:
        try:
            call_command('loaddata', fixture, verbosity=0)
            logger.info(f"✓ Loaded {fixture}")
        except Exception as e:
            logger.warning(f"⚠ Could not load {fixture}: {e}")

    move_all_texts_out_of_config()
    add_shipped_translations()
    logger.info("Default questionnaire fixtures loaded successfully")


@receiver(post_save, sender=Organization)
def create_default_questionnaires_for_organization(sender, instance, created, **kwargs):
    """
    Automatically clone all template questionnaires when a new organization is created.

    This ensures every organization starts with a complete set of questionnaires.
    Template questionnaires are those with organization=None and is_default=True.

    The "Professional Skills 360 Review" template (pk=1) will be marked as the
    organization's default questionnaire. All other cloned questionnaires will
    have is_default=False.
    """
    if not created:
        return

    # Get all template questionnaires using the templates() manager method
    template_questionnaires = Questionnaire.objects.templates().order_by('pk')

    if not template_questionnaires.exists():
        logger.warning("No template questionnaires found! Default questionnaires will not be cloned.")
        return

    # Clone each template for the new organization
    for template in template_questionnaires:
        cloned = clone_questionnaire_for_organization(template, instance)

        # Mark "Professional Skills 360 Review" as the organization's default
        # (it's the universal template that applies to all roles)
        if 'Professional Skills' in template.name:
            cloned.is_default = True
            cloned.save()
