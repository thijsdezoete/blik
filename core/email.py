"""
Custom email utilities that use Organization SMTP settings
"""
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend
from django.conf import settings
from .models import Organization


def get_email_backend():
    """
    Get email backend configured with Organization SMTP settings.
    Falls back to Django settings if no organization configured.
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
    except Exception as e:
        print(f"Error loading organization email settings: {e}")

    # Fall back to default Django email backend
    return EmailBackend(
        host=settings.EMAIL_HOST,
        port=settings.EMAIL_PORT,
        username=settings.EMAIL_HOST_USER,
        password=settings.EMAIL_HOST_PASSWORD,
        use_tls=settings.EMAIL_USE_TLS,
        fail_silently=False,
    )


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
