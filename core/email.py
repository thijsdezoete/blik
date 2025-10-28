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


def send_welcome_email(user, organization, password=None):
    """
    Send welcome email to newly registered user.

    Args:
        user: User object
        organization: Organization object
        password: Optional password to include in email (for admin-created accounts)

    Returns:
        Number of emails sent (0 or 1)
    """
    import random
    from django.template.loader import render_to_string
    from django.urls import reverse

    # Build login URL
    login_url = f'{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}{reverse("login")}'

    # Build Dreyfus model URL
    dreyfus_url = f'{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}/landing/dreyfus-model/'

    # Rotating facts about 360 feedback, psychology, and development
    facts = [
        {
            'title': 'The Power of 360 Feedback',
            'content': 'Research shows that <strong>360-degree feedback increases self-awareness by up to 30%</strong> and significantly improves leadership effectiveness. Unlike traditional top-down reviews, 360 feedback captures insights from peers, direct reports, and managers—giving you a complete picture of your impact.'
        },
        {
            'title': 'Blind Spots Matter',
            'content': 'Studies reveal that <strong>95% of people believe they are self-aware, but only 10-15% truly are</strong>. 360 feedback helps uncover blind spots—behaviors and impacts you might not see in yourself but are clear to others around you.'
        },
        {
            'title': 'Feedback Frequency',
            'content': '<strong>Organizations with regular feedback cycles see 14.9% lower turnover rates</strong> than those with annual reviews only. Continuous feedback creates a culture of growth and psychological safety, where people feel valued and heard.'
        },
        {
            'title': 'The Neuroscience of Feedback',
            'content': 'When we receive feedback, our brain activates the same regions involved in physical pain or reward. <strong>Framing feedback as growth opportunities rather than criticism activates reward pathways</strong>, making us more receptive and motivated to improve.'
        },
        {
            'title': 'Peer Feedback Impact',
            'content': '<strong>Peer feedback is often more accurate than manager feedback alone</strong> because peers see day-to-day behaviors and collaboration patterns. Combined perspectives create a more complete and actionable picture for development.'
        },
        {
            'title': 'Growth Mindset Research',
            'content': 'Carol Dweck\'s research shows that <strong>people with a growth mindset are 34% more likely to feel engaged at work</strong>. Regular 360 feedback reinforces growth mindset by showing that skills are developable, not fixed traits.'
        },
    ]

    # Select a random fact
    selected_fact = random.choice(facts)

    # Use different templates based on whether password is provided
    if password:
        # Admin-created account with credentials
        subject = f'Welcome to {settings.SITE_NAME} - Your Account is Ready'
        html_template = 'emails/welcome.html'
        text_template = 'emails/welcome.txt'
    else:
        # Invited member (already set their own password)
        subject = f'Welcome to {organization.name}!'
        html_template = 'emails/welcome_member.html'
        text_template = 'emails/welcome_member.txt'

    # Render email templates
    context = {
        'organization': organization,
        'user': user,
        'password': password,
        'login_url': login_url,
        'dreyfus_url': dreyfus_url,
        'site_name': settings.SITE_NAME,
        'fact_title': selected_fact['title'],
        'fact_content': selected_fact['content'],
    }

    html_message = render_to_string(html_template, context)
    text_message = render_to_string(text_template, context)

    return send_email(
        subject=subject,
        message=text_message,
        recipient_list=[user.email],
        html_message=html_message,
        from_email=organization.from_email if organization.from_email else None
    )
