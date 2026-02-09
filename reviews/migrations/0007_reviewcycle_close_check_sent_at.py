from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reviews', '0006_add_uuid_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='reviewcycle',
            name='close_check_sent_at',
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text='When the close check-in email was sent to the reviewee',
            ),
        ),
    ]
