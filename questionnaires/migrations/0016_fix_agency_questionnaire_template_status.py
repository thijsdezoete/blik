# Generated migration to fix Agency questionnaire template status

from django.db import migrations


def fix_agency_questionnaire_template_status(apps, schema_editor):
    """
    Fix Agency & Initiative Assessment to NOT be a default template.

    This questionnaire is used for the landing page growth hack and should
    NOT be cloned to all organizations automatically.
    """
    Questionnaire = apps.get_model('questionnaires', 'Questionnaire')

    # Update Agency questionnaire to not be a template
    updated = Questionnaire.objects.filter(
        name="Agency & Initiative Assessment",
        organization__isnull=True,
        is_default=True
    ).update(is_default=False)

    if updated:
        print(f"✓ Fixed Agency & Initiative Assessment (is_default=False)")
        print("  This questionnaire will no longer be cloned to new organizations")
    else:
        print("  Agency questionnaire already fixed or not found")


def reverse_fix(apps, schema_editor):
    """Reverse migration (set back to template)"""
    Questionnaire = apps.get_model('questionnaires', 'Questionnaire')

    Questionnaire.objects.filter(
        name="Agency & Initiative Assessment",
        organization__isnull=True
    ).update(is_default=True)


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaires', '0015_add_question_uuid'),
    ]

    operations = [
        migrations.RunPython(
            fix_agency_questionnaire_template_status,
            reverse_fix
        ),
    ]
