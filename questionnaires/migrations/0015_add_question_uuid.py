# Generated manually to handle UUID field addition with existing data
import uuid
from django.db import migrations, models


def generate_uuids(apps, schema_editor):
    """Generate UUIDs for all existing questions"""
    Question = apps.get_model('questionnaires', 'Question')
    for question in Question.objects.all():
        question.uuid = uuid.uuid4()
        question.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaires', '0014_add_action_items_field'),
    ]

    operations = [
        # Step 1: Add uuid field as nullable
        migrations.AddField(
            model_name='question',
            name='uuid',
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                help_text='Public identifier for API and URL usage (non-enumerable)',
                null=True,
            ),
        ),
        # Step 2: Generate UUIDs for existing records
        migrations.RunPython(generate_uuids, reverse_code=migrations.RunPython.noop),
        # Step 3: Make uuid unique and non-nullable
        migrations.AlterField(
            model_name='question',
            name='uuid',
            field=models.UUIDField(
                default=uuid.uuid4,
                unique=True,
                editable=False,
                db_index=True,
                help_text='Public identifier for API and URL usage (non-enumerable)',
            ),
        ),
    ]
