from django.db import migrations, models


class Migration(migrations.Migration):
    """Remove allow_registration from the model state only.

    The column stays in the database with a DB default, so the new code's
    INSERTs (which no longer name it) succeed and the old code, still running
    during the rollout, can read it. A later release drops the column.
    """

    dependencies = [
        ("core", "0011_organization_stripe_customer_id"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="organization",
                    name="allow_registration",
                ),
            ],
            database_operations=[
                migrations.AlterField(
                    model_name="organization",
                    name="allow_registration",
                    field=models.BooleanField(
                        default=False,
                        db_default=False,
                        help_text="Allow new users to register for this organization",
                        verbose_name="allow user registration",
                    ),
                ),
            ],
        ),
    ]
