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


def send_welcome_email(user, organization):
    """
    Send welcome email to newly registered user.

    Args:
        user: User object
        organization: Organization object
    """
    subject = f'Welcome to {organization.name} - 360 Feedback Platform'

    plain_message = f"""
Hello {user.username},

Welcome to {organization.name}'s 360 Feedback Platform!

Your account has been successfully created. You can now log in and start using the platform.

Getting Started:
- You can create feedback cycles for yourself
- Fill out questionnaires assigned to you
- View your feedback reports

If you have any questions or need assistance, please contact {organization.email}.

Best regards,
The {organization.name} Team
    """.strip()

    html_message = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background-color: #f9f9f9; }}
        .footer {{ padding: 20px; text-align: center; color: #666; font-size: 0.9em; }}
        .button {{ display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; margin: 10px 0; }}
        ul {{ padding-left: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Welcome to {organization.name}</h1>
        </div>
        <div class="content">
            <p>Hello <strong>{user.username}</strong>,</p>

            <p>Welcome to {organization.name}'s 360 Feedback Platform!</p>

            <p>Your account has been successfully created. You can now log in and start using the platform.</p>

            <h3>Getting Started:</h3>
            <ul>
                <li>You can create feedback cycles for yourself</li>
                <li>Fill out questionnaires assigned to you</li>
                <li>View your feedback reports</li>
            </ul>

            <p>If you have any questions or need assistance, please contact <a href="mailto:{organization.email}">{organization.email}</a>.</p>
        </div>
        <div class="footer">
            <p>Best regards,<br>The {organization.name} Team</p>
        </div>
    </div>
</body>
</html>
    """.strip()

    return send_email(
        subject=subject,
        message=plain_message,
        recipient_list=[user.email],
        html_message=html_message,
        from_email=organization.from_email if organization.from_email else None
    )
