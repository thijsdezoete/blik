from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model with created and updated timestamps"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(TimeStampedModel):
    """Organization model for multi-tenant support"""
    name = models.CharField(max_length=255)
    email = models.EmailField()

    # Email settings
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.IntegerField(default=587)
    smtp_username = models.CharField(max_length=255, blank=True)
    smtp_password = models.CharField(max_length=255, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    from_email = models.EmailField(blank=True)

    # Report settings
    min_responses_for_anonymity = models.IntegerField(
        default=3,
        help_text='Minimum number of responses required to show results (for anonymity). Set to 1 for small teams.'
    )

    # Registration settings
    allow_registration = models.BooleanField(
        default=False,
        help_text='Allow new users to register for this organization'
    )
    default_users_can_create_cycles = models.BooleanField(
        default=False,
        help_text='By default, new users can create cycles for others (not just themselves)'
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'organizations'
        ordering = ['name']

    def __str__(self):
        return self.name
