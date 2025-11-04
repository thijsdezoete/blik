# Generated manually for UUID field addition with data migration
import uuid
from django.db import migrations, models


def generate_apitoken_uuids(apps, schema_editor):
    """Generate UUIDs for existing APIToken records"""
    APIToken = apps.get_model('api', 'APIToken')
    for token in APIToken.objects.all():
        token.uuid = uuid.uuid4()
        token.save(update_fields=['uuid'])


def generate_webhook_uuids(apps, schema_editor):
    """Generate UUIDs for existing WebhookEndpoint records"""
    WebhookEndpoint = apps.get_model('api', 'WebhookEndpoint')
    for webhook in WebhookEndpoint.objects.all():
        webhook.uuid = uuid.uuid4()
        webhook.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_add_webhook_delivery_uuid'),
    ]

    operations = [
        # APIToken UUID field
        migrations.AddField(
            model_name='apitoken',
            name='uuid',
            field=models.UUIDField(null=True, editable=False, db_index=True, help_text='Public identifier for API and URL usage (non-enumerable)'),
        ),
        migrations.RunPython(generate_apitoken_uuids, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='apitoken',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True, help_text='Public identifier for API and URL usage (non-enumerable)'),
        ),

        # WebhookEndpoint UUID field
        migrations.AddField(
            model_name='webhookendpoint',
            name='uuid',
            field=models.UUIDField(null=True, editable=False, db_index=True, help_text='Public identifier for API and URL usage (non-enumerable)'),
        ),
        migrations.RunPython(generate_webhook_uuids, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='webhookendpoint',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True, help_text='Public identifier for API and URL usage (non-enumerable)'),
        ),
    ]
