from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_add_auto_send_report_email'),
    ]

    operations = [
        migrations.CreateModel(
            name='UpgradeStep',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('applied_at', models.DateTimeField(auto_now_add=True)),
                ('success', models.BooleanField(default=False)),
                ('error', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'upgrade_steps',
            },
        ),
    ]
