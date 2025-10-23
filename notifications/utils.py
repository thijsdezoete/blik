from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from reviews.models import ReviewerToken


def send_feedback_invitation(token, reviewer_email=None):
    """Send feedback invitation email for a reviewer token"""

    feedback_url = f"{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost:8000'}/feedback/{token.token}/"

    # Use http in development, https in production
    protocol = 'http' if settings.DEBUG else 'https'
    full_url = f"{protocol}://{feedback_url}"

    context = {
        'reviewee_name': token.cycle.reviewee.name,
        'category': token.get_category_display(),
        'feedback_url': full_url,
        'token': token,
    }

    subject = f"360 Feedback Request for {token.cycle.reviewee.name}"

    # Render text email
    message = render_to_string('notifications/feedback_invitation.txt', context)

    # Render HTML email
    html_message = render_to_string('notifications/feedback_invitation.html', context)

    # Send email
    if reviewer_email:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reviewer_email],
            html_message=html_message,
            fail_silently=False,
        )
        return True

    return False


def send_multiple_invitations(tokens, emails):
    """Send invitations for multiple tokens with corresponding emails"""
    if len(tokens) != len(emails):
        raise ValueError("Number of tokens must match number of emails")

    results = []
    for token, email in zip(tokens, emails):
        try:
            success = send_feedback_invitation(token, email)
            results.append({'token': token, 'email': email, 'success': success})
        except Exception as e:
            results.append({'token': token, 'email': email, 'success': False, 'error': str(e)})

    return results
