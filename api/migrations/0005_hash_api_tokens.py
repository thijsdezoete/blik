import hashlib

from django.db import migrations, models


def hash_existing_tokens(apps, schema_editor):
    """Store each token as its SHA-256; clients keep sending the same token."""
    APIToken = apps.get_model('api', 'APIToken')
    for token in APIToken.objects.all():
        token.prefix = token.token[:8]
        token.token = hashlib.sha256(token.token.encode()).hexdigest()
        token.save(update_fields=['prefix', 'token'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0004_alter_webhookdelivery_delivery_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='apitoken',
            name='prefix',
            field=models.CharField(blank=True, editable=False, help_text='First characters of the token, to recognize it', max_length=8, verbose_name='prefix'),
        ),
        # Irreversible: the raw tokens are gone after this.
        migrations.RunPython(hash_existing_tokens, migrations.RunPython.noop),
    ]
