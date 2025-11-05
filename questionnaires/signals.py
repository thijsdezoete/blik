from django.db.models.signals import post_save
from django.db.backends.signals import connection_created
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.core.management import call_command
from core.models import Organization
from .models import Questionnaire, QuestionSection, Question
import logging

logger = logging.getLogger(__name__)


def clone_questionnaire_for_organization(questionnaire, organization):
    """
    Clone a template questionnaire with all sections and questions for a specific organization.

    Args:
        questionnaire: The template questionnaire to clone (should have organization=None)
        organization: The organization to clone the questionnaire for

    Returns:
        The cloned questionnaire instance
    """
    # Clone the questionnaire by creating a new instance with copied fields
    original_pk = questionnaire.pk
    cloned_questionnaire = Questionnaire.objects.create(
        organization=organization,
        name=questionnaire.name,
        description=questionnaire.description,
        is_default=False,  # Only templates should be marked as default
        is_active=questionnaire.is_active
    )

    # Clone all sections
    sections = QuestionSection.objects.filter(questionnaire_id=original_pk).order_by('order')
    section_mapping = {}  # Map original section PK to cloned section

    for section in sections:
        original_section_pk = section.pk
        section.pk = None
        section.id = None
        section.questionnaire = cloned_questionnaire
        section.save()
        section_mapping[original_section_pk] = section

    # Clone all questions
    for original_section_pk, cloned_section in section_mapping.items():
        questions = Question.objects.filter(section_id=original_section_pk).order_by('order')
        for question in questions:
            question.pk = None
            question.id = None
            question.section = cloned_section
            question.save()

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
