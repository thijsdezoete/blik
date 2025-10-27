# Generated manually for security fix
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_remove_slug_field'),
    ]

    operations = [
        # Add new encrypted field
        migrations.AddField(
            model_name='organization',
            name='smtp_password_encrypted',
            field=models.BinaryField(blank=True, null=True),
        ),
        # Remove old plaintext field
        migrations.RemoveField(
            model_name='organization',
            name='smtp_password',
        ),
    ]
