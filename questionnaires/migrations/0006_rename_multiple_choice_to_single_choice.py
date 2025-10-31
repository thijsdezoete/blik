# Migration to rename 'multiple_choice' to 'single_choice' and add new 'multiple_choice' type

from django.db import migrations, models


def migrate_multiple_choice_to_single_choice(apps, schema_editor):
    """
    Migrate existing 'multiple_choice' questions to 'single_choice'
    since the old implementation was actually single choice (dropdown)
    """
    Question = apps.get_model('questionnaires', 'Question')
    Question.objects.filter(question_type='multiple_choice').update(question_type='single_choice')


def reverse_migration(apps, schema_editor):
    """
    Reverse migration - change 'single_choice' back to 'multiple_choice'
    """
    Question = apps.get_model('questionnaires', 'Question')
    Question.objects.filter(question_type='single_choice').update(question_type='multiple_choice')


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaires', '0005_ensure_software_engineering_template'),
    ]

    operations = [
        # First, update the field to accept both old and new values
        migrations.AlterField(
            model_name='question',
            name='question_type',
            field=models.CharField(
                choices=[
                    ('rating', 'Rating Scale'),
                    ('likert', 'Likert Scale'),
                    ('text', 'Free Text'),
                    ('single_choice', 'Single Choice'),
                    ('multiple_choice', 'Multiple Choice'),
                ],
                max_length=20
            ),
        ),
        # Then migrate the data
        migrations.RunPython(
            migrate_multiple_choice_to_single_choice,
            reverse_migration
        ),
    ]
