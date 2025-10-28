from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet


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
    smtp_password_encrypted = models.BinaryField(blank=True, null=True)
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

    def set_smtp_password(self, raw_password):
        """
        Encrypt and store SMTP password.

        Args:
            raw_password (str): The plaintext SMTP password

        Note: Requires ENCRYPTION_KEY to be set in settings
        """
        if raw_password:
            encryption_key = getattr(settings, 'ENCRYPTION_KEY', None)
            if not encryption_key:
                raise ValueError(
                    'ENCRYPTION_KEY not configured in settings. '
                    'Generate with: from cryptography.fernet import Fernet; Fernet.generate_key()'
                )
            f = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
            self.smtp_password_encrypted = f.encrypt(raw_password.encode())
        else:
            self.smtp_password_encrypted = None

    def get_smtp_password(self):
        """
        Decrypt and return SMTP password.

        Returns:
            str or None: The decrypted SMTP password, or None if not set
        """
        if self.smtp_password_encrypted:
            encryption_key = getattr(settings, 'ENCRYPTION_KEY', None)
            if not encryption_key:
                raise ValueError('ENCRYPTION_KEY not configured in settings')
            f = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
            return f.decrypt(self.smtp_password_encrypted).decode()
        return None

    @property
    def smtp_password(self):
        """Backward compatibility property"""
        return self.get_smtp_password()

    @smtp_password.setter
    def smtp_password(self, value):
        """Backward compatibility setter"""
        self.set_smtp_password(value)


class WelcomeEmailFact(TimeStampedModel):
    """
    Educational facts about 360 feedback, psychology, and development.
    These are randomly selected and shown in welcome emails.
    """
    title = models.CharField(
        max_length=255,
        help_text='Short title for the fact (e.g., "The Power of 360 Feedback")'
    )
    content = models.TextField(
        help_text='The fact content. Can include HTML tags like <strong> for emphasis.'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Only active facts will be shown in emails'
    )
    display_order = models.IntegerField(
        default=0,
        help_text='Optional ordering (lower numbers shown first when not randomizing)'
    )

    class Meta:
        db_table = 'welcome_email_facts'
        ordering = ['display_order', 'created_at']
        verbose_name = 'Welcome Email Fact'
        verbose_name_plural = 'Welcome Email Facts'

    def __str__(self):
        return self.title
