"""
Service functions for review cycles
"""
import random
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from core.email import send_email
from datetime import timedelta
from django.db.models import Q
from .models import ReviewCycle, ReviewerToken


def assign_tokens_to_emails(cycle, email_assignments):
    """
    Assign reviewer tokens to email addresses with smart randomization.

    Args:
        cycle: ReviewCycle instance
        email_assignments: dict like {
            'self': ['reviewee@example.com'],
            'peer': ['peer1@example.com', 'peer2@example.com'],
            'manager': ['manager@example.com'],
            'direct_report': []
        }

    Returns:
        dict: Statistics about assignments
    """
    stats = {
        'assigned': 0,
        'sent': 0,
        'errors': []
    }

    for category, emails in email_assignments.items():
        if not emails:
            continue

        # Get unassigned tokens for this category
        available_tokens = list(
            cycle.tokens.filter(
                category=category,
                reviewer_email__isnull=True
            )
        )

        if len(emails) > len(available_tokens):
            stats['errors'].append(
                f"Not enough tokens for {category}: need {len(emails)}, have {len(available_tokens)}"
            )
            continue

        # Randomly shuffle tokens to prevent any pattern linking
        random.shuffle(available_tokens)

        # Assign emails to tokens
        for email, token in zip(emails, available_tokens):
            token.reviewer_email = email.strip().lower()
            token.save()
            stats['assigned'] += 1

    return stats


def send_reviewer_invitations(cycle, token_ids=None):
    """
    Send email invitations to reviewers.

    Args:
        cycle: ReviewCycle instance
        token_ids: Optional list of specific token IDs to send (defaults to all with emails)

    Returns:
        dict: Statistics about emails sent
    """
    stats = {
        'sent': 0,
        'errors': []
    }

    # Get tokens to send invitations for
    tokens = cycle.tokens.filter(reviewer_email__isnull=False)

    if token_ids:
        tokens = tokens.filter(id__in=token_ids)
    else:
        # Only send to tokens that haven't been sent yet and aren't completed
        tokens = tokens.filter(invitation_sent_at__isnull=True, completed_at__isnull=True)

    for token in tokens:
        try:
            # Generate feedback URL
            feedback_url = f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}/feedback/{token.token}/"

            # Render email templates
            context = {
                'reviewee_name': cycle.reviewee.name,
                'category': token.get_category_display(),
                'feedback_url': feedback_url,
                'questionnaire_name': cycle.questionnaire.name,
            }

            html_message = render_to_string('emails/reviewer_invitation.html', context)
            text_message = render_to_string('emails/reviewer_invitation.txt', context)

            # Send email
            send_email(
                subject=f'360 Feedback Request: {cycle.reviewee.name}',
                message=text_message,
                recipient_list=[token.reviewer_email],
                html_message=html_message,
            )

            # Mark as sent
            token.invitation_sent_at = timezone.now()
            token.save()

            stats['sent'] += 1

        except Exception as e:
            stats['errors'].append(f"Failed to send to {token.reviewer_email}: {str(e)}")

    return stats


def send_reminder_emails(cycle, token_ids=None):
    """
    Send reminder emails to reviewers who haven't completed feedback.

    Args:
        cycle: ReviewCycle instance
        token_ids: Optional list of specific token IDs to remind

    Returns:
        dict: Statistics about reminders sent
    """
    stats = {
        'sent': 0,
        'errors': []
    }

    # Get incomplete tokens with emails that have been invited
    tokens = cycle.tokens.filter(
        reviewer_email__isnull=False,
        invitation_sent_at__isnull=False,
        completed_at__isnull=True
    )

    if token_ids:
        tokens = tokens.filter(id__in=token_ids)

    for token in tokens:
        try:
            # Generate feedback URL
            feedback_url = f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}/feedback/{token.token}/"

            # Render email templates
            context = {
                'reviewee_name': cycle.reviewee.name,
                'category': token.get_category_display(),
                'feedback_url': feedback_url,
                'questionnaire_name': cycle.questionnaire.name,
            }

            html_message = render_to_string('emails/reviewer_reminder.html', context)
            text_message = render_to_string('emails/reviewer_reminder.txt', context)

            # Send email
            send_email(
                subject=f'Reminder: 360 Feedback Request for {cycle.reviewee.name}',
                message=text_message,
                recipient_list=[token.reviewer_email],
                html_message=html_message,
            )

            # Update last reminder sent timestamp
            token.last_reminder_sent_at = timezone.now()
            token.save(update_fields=['last_reminder_sent_at'])

            stats['sent'] += 1

        except Exception as e:
            stats['errors'].append(f"Failed to send reminder to {token.reviewer_email}: {str(e)}")

    return stats


def send_reviewee_notifications(cycle, request=None):
    """
    Send emails to reviewee when a cycle is created:
    1. Self-assessment link
    2. Invitation links to share with others

    Args:
        cycle: ReviewCycle instance
        request: Optional request object for building absolute URLs

    Returns:
        dict: Statistics about emails sent
    """
    stats = {
        'sent': 0,
        'errors': []
    }

    if not cycle.reviewee.email:
        stats['errors'].append(f"No email address for reviewee {cycle.reviewee.name}")
        return stats

    # Build absolute URLs
    if request:
        base_url = f"{request.scheme}://{request.get_host()}"
    else:
        base_url = f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}"

    # 1. Send self-assessment email
    try:
        self_assessment_url = f"{base_url}{reverse('reviews:claim_token', kwargs={'invitation_token': cycle.invitation_token_self})}"

        context = {
            'reviewee': cycle.reviewee,
            'cycle': cycle,
            'self_assessment_url': self_assessment_url,
        }

        html_message = render_to_string('emails/reviewee_self_assessment.html', context)
        text_message = render_to_string('emails/reviewee_self_assessment.txt', context)

        send_email(
            subject=f'Complete Your Self-Assessment: {cycle.questionnaire.name}',
            message=text_message,
            recipient_list=[cycle.reviewee.email],
            html_message=html_message,
        )

        stats['sent'] += 1

    except Exception as e:
        stats['errors'].append(f"Failed to send self-assessment email: {str(e)}")

    # 2. Send invitation links email
    try:
        peer_url = f"{base_url}{reverse('reviews:claim_token', kwargs={'invitation_token': cycle.invitation_token_peer})}"
        manager_url = f"{base_url}{reverse('reviews:claim_token', kwargs={'invitation_token': cycle.invitation_token_manager})}"
        direct_report_url = f"{base_url}{reverse('reviews:claim_token', kwargs={'invitation_token': cycle.invitation_token_direct_report})}"

        context = {
            'reviewee': cycle.reviewee,
            'cycle': cycle,
            'peer_url': peer_url,
            'manager_url': manager_url,
            'direct_report_url': direct_report_url,
        }

        html_message = render_to_string('emails/reviewee_invitation_links.html', context)
        text_message = render_to_string('emails/reviewee_invitation_links.txt', context)

        send_email(
            subject=f'Share Your 360 Feedback Links: {cycle.questionnaire.name}',
            message=text_message,
            recipient_list=[cycle.reviewee.email],
            html_message=html_message,
        )

        stats['sent'] += 1

    except Exception as e:
        stats['errors'].append(f"Failed to send invitation links email: {str(e)}")

    return stats


def send_close_check_emails(dry_run=False):
    """
    Send check-in emails to reviewees whose invite-link cycles have been
    open for at least 7 days and have at least one completed review.

    Args:
        dry_run: If True, find eligible cycles but don't send emails.

    Returns:
        dict: Statistics about emails sent
    """
    stats = {
        'sent': 0,
        'eligible': 0,
        'errors': [],
    }

    cutoff = timezone.now() - timedelta(days=7)

    cycles = ReviewCycle.objects.filter(
        status='active',
        close_check_sent_at__isnull=True,
        created_at__lte=cutoff,
    ).filter(
        tokens__completed_at__isnull=False,
    ).distinct().select_related('reviewee', 'questionnaire')

    stats['eligible'] = cycles.count()

    if dry_run:
        return stats

    base_url = f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}"

    for cycle in cycles:
        try:
            if not cycle.reviewee.email:
                stats['errors'].append(
                    f"No email for reviewee {cycle.reviewee.name} (cycle {cycle.uuid})"
                )
                continue

            completed_count = cycle.tokens.filter(completed_at__isnull=False).count()
            total_count = cycle.tokens.count()
            dashboard_url = f"{base_url}/dashboard/cycles/{cycle.uuid}/"

            context = {
                'reviewee': cycle.reviewee,
                'cycle': cycle,
                'questionnaire_name': cycle.questionnaire.name,
                'completed_count': completed_count,
                'total_count': total_count,
                'dashboard_url': dashboard_url,
            }

            html_message = render_to_string('emails/cycle_close_check.html', context)
            text_message = render_to_string('emails/cycle_close_check.txt', context)

            send_email(
                subject=f'Review Check-In: {cycle.questionnaire.name}',
                message=text_message,
                recipient_list=[cycle.reviewee.email],
                html_message=html_message,
            )

            cycle.close_check_sent_at = timezone.now()
            cycle.save(update_fields=['close_check_sent_at'])

            stats['sent'] += 1

        except Exception as e:
            stats['errors'].append(
                f"Failed to send close check for cycle {cycle.uuid}: {str(e)}"
            )

    return stats
