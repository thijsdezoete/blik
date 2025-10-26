from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import Organization
from .models import Questionnaire, QuestionSection, Question


def clone_questionnaire_for_organization(questionnaire, organization):
    """
    Clone a template questionnaire with all sections and questions for a specific organization.

    Args:
        questionnaire: The template questionnaire to clone (should have organization=None)
        organization: The organization to clone the questionnaire for

    Returns:
        The cloned questionnaire instance
    """
    # Clone the questionnaire
    original_pk = questionnaire.pk
    questionnaire.pk = None
    questionnaire.id = None
    questionnaire.organization = organization
    questionnaire.is_default = False  # Only templates should be marked as default
    questionnaire.save()

    cloned_questionnaire = questionnaire

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


@receiver(post_save, sender=Organization)
def create_default_questionnaires_for_organization(sender, instance, created, **kwargs):
    """
    Automatically clone all default questionnaires when a new organization is created.

    This ensures every organization starts with a complete set of questionnaires.
    Template questionnaires are those with organization=None and is_default=True.
    """
    if not created:
        return

    # Get all template questionnaires using the templates() manager method
    template_questionnaires = Questionnaire.objects.templates()

    # Clone each template for the new organization
    for template in template_questionnaires:
        clone_questionnaire_for_organization(template, instance)
