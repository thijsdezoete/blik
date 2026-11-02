from django.db import models
from django.conf import settings
from django.utils.translation import gettext, gettext_lazy as _
from cryptography.fernet import Fernet


class TimeStampedModel(models.Model):
    """Abstract base model with created and updated timestamps"""
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


class Organization(TimeStampedModel):
    """Organization model for multi-tenant support"""
    name = models.CharField(_('name'), max_length=255)
    email = models.EmailField(_('email'))

    # Email settings
    smtp_host = models.CharField(_('SMTP host'), max_length=255, blank=True)
    smtp_port = models.IntegerField(_('SMTP port'), default=587)
    smtp_username = models.CharField(_('SMTP username'), max_length=255, blank=True)
    smtp_password_encrypted = models.BinaryField(_('encrypted SMTP password'), blank=True, null=True)
    smtp_use_tls = models.BooleanField(_('use TLS'), default=True)
    from_email = models.EmailField(_('from address'), blank=True)

    # Report settings
    min_responses_for_anonymity = models.IntegerField(
        default=3,
        help_text=_('Minimum number of responses required to show results (for anonymity). Set to 1 for small teams.'),
        verbose_name=_('minimum responses for anonymity')
    )
    auto_send_report_email = models.BooleanField(
        default=True,
        help_text=_('Automatically send email to reviewee when their report is generated'),
        verbose_name=_('automatically send report email')
    )

    # Billing: the one Stripe customer every checkout, invoice and portal session uses
    stripe_customer_id = models.CharField(_('Stripe customer ID'), max_length=255, blank=True, db_index=True)

    # Registration settings
    default_users_can_create_cycles = models.BooleanField(
        default=False,
        help_text=_('By default, new users can create cycles for others (not just themselves)'),
        verbose_name=_('new users can create cycles for others')
    )

    # Validated against settings.LANGUAGES where it is set, so the language list is never frozen
    # into a migration.
    default_language = models.CharField(
        max_length=20,
        default=settings.LANGUAGE_CODE,
        help_text=_('Language of emails and feedback forms, unless a person has their own'),
        verbose_name=_('default language')
    )

    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        verbose_name = _('organization')
        verbose_name_plural = _('organizations')
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
        help_text=_('Short title for the fact (e.g., "The Power of 360 Feedback")'),
        verbose_name=_('title')
    )
    content = models.TextField(
        help_text=_('The fact content. Can include HTML tags like <strong> for emphasis.'),
        verbose_name=_('content')
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_('Only active facts will be shown in emails'),
        verbose_name=_('active')
    )
    display_order = models.IntegerField(
        default=0,
        help_text=_('Optional ordering (lower numbers shown first when not randomizing)'),
        verbose_name=_('display order')
    )

    class Meta:
        db_table = 'welcome_email_facts'
        ordering = ['display_order', 'created_at']
        verbose_name = _('Welcome Email Fact')
        verbose_name_plural = _('Welcome Email Facts')

    def __str__(self):
        return self.title


class UpgradeStep(models.Model):
    """Tracks one-time data upgrade steps that run on deploy."""
    name = models.CharField(_('name'), max_length=255, unique=True)
    applied_at = models.DateTimeField(_('applied at'), auto_now_add=True)
    success = models.BooleanField(_('success'), default=False)
    error = models.TextField(_('error'), blank=True, default='')

    class Meta:
        verbose_name = _('upgrade step')
        verbose_name_plural = _('upgrade steps')
        db_table = 'upgrade_steps'

    def __str__(self):
        status = gettext('OK') if self.success else gettext('FAILED')
        return f'{self.name} [{status}]'
