from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reviews', '0007_reviewcycle_close_check_sent_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='reviewertoken',
            name='language',
            field=models.CharField(
                blank=True,
                choices=settings.LANGUAGES,
                max_length=10,
                null=True,
            ),
        ),
    ]
