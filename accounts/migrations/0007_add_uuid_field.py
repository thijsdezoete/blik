# Generated manually for UUID field addition with data migration
import uuid
from django.db import migrations, models


def generate_uuids(apps, schema_editor):
    """Generate UUIDs for existing Reviewee records"""
    Reviewee = apps.get_model('accounts', 'Reviewee')
    for reviewee in Reviewee.objects.all():
        reviewee.uuid = uuid.uuid4()
        reviewee.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_add_has_seen_welcome'),
    ]

    operations = [
        # Step 1: Add UUID field as nullable
        migrations.AddField(
            model_name='reviewee',
            name='uuid',
            field=models.UUIDField(null=True, editable=False, db_index=True, help_text='Public identifier for API and URL usage (non-enumerable)'),
        ),
        # Step 2: Generate UUIDs for existing records
        migrations.RunPython(generate_uuids, reverse_code=migrations.RunPython.noop),
        # Step 3: Make UUID field non-nullable and unique
        migrations.AlterField(
            model_name='reviewee',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True, help_text='Public identifier for API and URL usage (non-enumerable)'),
        ),
    ]
