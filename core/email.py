"""
Custom email utilities that use Organization SMTP settings
"""
import logging

from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.mail.backends.smtp import EmailBackend
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _, gettext_lazy
from .languages import user_language
from .models import Organization

logger = logging.getLogger(__name__)


def get_email_backend():
    """
    Get email backend configured with Organization SMTP settings.
    Falls back to the backend in Django settings if no organization SMTP host
    is configured — that fallback must honour EMAIL_BACKEND, otherwise console
    and locmem (test) backends are bypassed in favour of a real SMTP connection.
    """
    try:
        org = Organization.objects.filter(is_active=True).first()

        if org and org.smtp_host:
            # Use organization's SMTP settings
            return EmailBackend(
                host=org.smtp_host,
                port=org.smtp_port,
                username=org.smtp_username,
                password=org.smtp_password,
                use_tls=org.smtp_use_tls,
                fail_silently=False,
            )
    except Exception:
        logger.exception('Error loading organization email settings')

    return get_connection(fail_silently=False)


def get_from_email():
    """Get the from_email from Organization or fall back to Django settings"""
    try:
        org = Organization.objects.filter(is_active=True).first()
        if org and org.from_email:
            return org.from_email
    except Exception:
        pass

    return settings.DEFAULT_FROM_EMAIL


def send_email(subject, message, recipient_list, html_message=None, from_email=None):
    """
    Send email using Organization SMTP settings.

    Args:
        subject: Email subject
        message: Plain text message
        recipient_list: List of recipient email addresses
        html_message: Optional HTML version of message
        from_email: Optional from email (defaults to organization setting)

    Returns:
        Number of emails sent (0 or 1)
    """
    if from_email is None:
        from_email = get_from_email()

    backend = get_email_backend()

    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=from_email,
        to=recipient_list,
        connection=backend,
    )

    if html_message:
        email.attach_alternative(html_message, 'text/html')

    return email.send()


def send_password_reset_email(user, token):
    """
    Send password reset email to user.

    Args:
        user: User object
        token: PasswordResetToken object

    Returns:
        Number of emails sent (0 or 1)
    """
    from django.template.loader import render_to_string
    from .url import get_absolute_url

    # Build reset URL
    reset_url = get_absolute_url('reset_password', token.token)

    with translation.override(user_language(user)):
        subject = _('Reset your %(site_name)s password') % {'site_name': settings.SITE_NAME}

        context = {
            'user': user,
            'reset_url': reset_url,
            'site_name': settings.SITE_NAME,
        }

        html_message = render_to_string('emails/password_reset.html', context)
        text_message = render_to_string('emails/password_reset.txt', context)

    return send_email(
        subject=subject,
        message=text_message,
        recipient_list=[user.email],
        html_message=html_message
    )


def inviter_name(user):
    """How an email names the person who invited someone: their full name, else their email. None without a user."""
    if user is None:
        return None
    return user.get_full_name() or user.email or None


def send_welcome_email(user, organization, password=None, invited_by=None):
    """
    Send welcome email to newly registered user.

    Args:
        user: User object
        organization: Organization object
        password: Optional password to include in email (for admin-created accounts)
        invited_by: Optional user who invited them (for invited members)

    Returns:
        Number of emails sent (0 or 1)
    """
    from django.template.loader import render_to_string
    from subscriptions.emails import SUPPORT_EMAIL
    from .url import get_absolute_url

    with translation.override(user_language(user, organization)):
        # Use different templates based on whether password is provided
        if password:
            # Admin-created account with credentials
            subject = _('Welcome to %(site_name)s. Your account is ready') % {'site_name': settings.SITE_NAME}
            template = 'emails/welcome'
        else:
            # Invited member (already set their own password)
            subject = _('Welcome to %(organization)s on %(site_name)s') % {
                'organization': organization.name, 'site_name': settings.SITE_NAME}
            template = 'emails/welcome_member'

        context = {
            'organization': organization,
            'user': user,
            'password': password,
            'login_url': get_absolute_url('login'),
            'create_cycle_url': get_absolute_url('review_cycle_create'),
            'inviter_name': inviter_name(invited_by),
            'site_name': settings.SITE_NAME,
            'support_email': SUPPORT_EMAIL,
        }

        html_message = render_to_string(f'{template}.html', context)
        text_message = render_to_string(f'{template}.txt', context)

    return send_email(
        subject=subject,
        message=text_message,
        recipient_list=[user.email],
        html_message=html_message,
        from_email=organization.from_email if organization.from_email else None
    )


def _send_account_notice(email, language, subject, template, context):
    """Render emails/<template>.html and .txt in the recipient's language and send them to one address.

    subject is a lazy text with a %(site_name)s placeholder.
    """
    from django.template.loader import render_to_string
    from django.utils import timezone
    from django.utils.formats import date_format

    with translation.override(language):
        now = timezone.localtime()
        context = {
            'site_name': settings.SITE_NAME,
            'date': date_format(now, 'DATE_FORMAT'),
            'time': date_format(now, 'H:i'),
            **context,
        }
        subject = str(subject) % {'site_name': settings.SITE_NAME}
        html_message = render_to_string(f'emails/{template}.html', context)
        text_message = render_to_string(f'emails/{template}.txt', context)

    return send_email(subject=subject, message=text_message, recipient_list=[email], html_message=html_message)


def send_password_changed_email(user):
    """Security notice after the user's password changed, with a way out if it was not them."""
    from .url import get_absolute_url

    return _send_account_notice(
        user.email, user_language(user), gettext_lazy('Your %(site_name)s password was changed'),
        'password_changed', {'user': user, 'reset_url': get_absolute_url('forgot_password')},
    )


def send_email_changed_email(user, old_email):
    """Security notice to the old address after the user's email address changed."""
    profile = getattr(user, 'profile', None)

    return _send_account_notice(
        old_email, user_language(user),
        gettext_lazy('The email address of your %(site_name)s account was changed'),
        'email_changed', {
            'user': user,
            'old_email': old_email,
            'new_email': user.email,
            'organization': getattr(profile, 'organization', None),
        },
    )


def send_account_deleted_email(email, language, organization_name=None, had_subscription=False):
    """Confirmation that a deletion the user asked for is done: their account, or with organization_name, their
    whole organization. Sent after the data is gone, so it takes plain values."""
    if organization_name:
        subject = gettext_lazy('Your organization was deleted from %(site_name)s')
    else:
        subject = gettext_lazy('Your %(site_name)s account was deleted')

    return _send_account_notice(email, language, subject, 'account_deleted', {
        'email': email,
        'organization_name': organization_name,
        'had_subscription': had_subscription,
    })
