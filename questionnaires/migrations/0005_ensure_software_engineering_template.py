# Generated migration to ensure Software Engineering questionnaire is marked as default template

from django.db import migrations


def clone_questionnaire_for_org(template, organization, Questionnaire, QuestionSection, Question):
    """
    Clone a template questionnaire for a specific organization.
    This is a migration-safe version that doesn't rely on signals.
    """
    # Clone the questionnaire
    original_pk = template.pk
    template.pk = None
    template.id = None
    template.organization = organization
    template.is_default = False  # Only templates should be marked as default
    template.save()

    cloned_questionnaire = template

    # Clone all sections
    sections = QuestionSection.objects.filter(questionnaire_id=original_pk).order_by('order')
    section_mapping = {}

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


def ensure_software_engineering_template(apps, schema_editor):
    """
    Ensure Software Engineering 360 Review template is marked as default and
    clone it to all existing organizations that don't have it.

    This fixes an issue where the fixture file was updated but existing databases
    still had the old is_default=False value, preventing the questionnaire from
    being cloned to new organizations.
    """
    Questionnaire = apps.get_model('questionnaires', 'Questionnaire')
    QuestionSection = apps.get_model('questionnaires', 'QuestionSection')
    Question = apps.get_model('questionnaires', 'Question')
    Organization = apps.get_model('core', 'Organization')

    # Find the Software Engineering template (organization=None)
    try:
        software_eng_template = Questionnaire.objects.get(
            name="Software Engineering 360 Review",
            organization__isnull=True
        )

        # Update is_default if needed
        if not software_eng_template.is_default:
            software_eng_template.is_default = True
            software_eng_template.save()
            print("✓ Updated Software Engineering template to is_default=True")
        else:
            print("✓ Software Engineering template already has is_default=True")

        # Clone to existing organizations that don't have it
        cloned_count = 0
        skipped_count = 0

        for org in Organization.objects.all():
            # Check if org already has this questionnaire
            has_questionnaire = Questionnaire.objects.filter(
                organization=org,
                name="Software Engineering 360 Review"
            ).exists()

            if has_questionnaire:
                skipped_count += 1
                continue

            # Clone the template for this org
            # Need to re-fetch the template to get a fresh instance for cloning
            template = Questionnaire.objects.get(pk=software_eng_template.pk)
            clone_questionnaire_for_org(template, org, Questionnaire, QuestionSection, Question)
            cloned_count += 1

        if cloned_count > 0:
            print(f"✓ Cloned Software Engineering questionnaire to {cloned_count} organization(s)")
        if skipped_count > 0:
            print(f"  Skipped {skipped_count} organization(s) that already had it")

    except Questionnaire.DoesNotExist:
        print("⚠ Software Engineering template not found - may need to run loaddata")
    except Questionnaire.MultipleObjectsReturned:
        # Multiple templates found - update all of them
        templates = Questionnaire.objects.filter(
            name="Software Engineering 360 Review",
            organization__isnull=True
        )
        for template in templates:
            if not template.is_default:
                template.is_default = True
                template.save()
        print(f"✓ Updated {templates.count()} Software Engineering template(s) to is_default=True")


def reverse_software_engineering_template(apps, schema_editor):
    """
    Reverse operation - set Software Engineering template back to is_default=False.

    NOTE: We do NOT delete the cloned questionnaires from organizations because:
    1. They may be referenced by review cycles (foreign key constraint)
    2. They provide value even if not marked as a template
    3. Destructive operations should be avoided in reversible migrations
    """
    Questionnaire = apps.get_model('questionnaires', 'Questionnaire')

    # Revert template to is_default=False
    try:
        software_eng = Questionnaire.objects.get(
            name="Software Engineering 360 Review",
            organization__isnull=True
        )
        software_eng.is_default = False
        software_eng.save()
        print("Reverted Software Engineering template to is_default=False")
    except Questionnaire.DoesNotExist:
        pass
    except Questionnaire.MultipleObjectsReturned:
        templates = Questionnaire.objects.filter(
            name="Software Engineering 360 Review",
            organization__isnull=True
        )
        templates.update(is_default=False)
        print(f"Reverted {templates.count()} Software Engineering template(s) to is_default=False")

    # Note: Cloned questionnaires are left in place for existing organizations


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaires', '0004_add_agency_questionnaire'),
    ]

    operations = [
        migrations.RunPython(
            ensure_software_engineering_template,
            reverse_software_engineering_template
        ),
    ]
