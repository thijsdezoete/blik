"""Account and organization management services."""
import json
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import Organization
from accounts.models import UserProfile, Reviewee
from reviews.models import ReviewCycle, ReviewerToken, Response
from reports.models import Report
from questionnaires.models import Questionnaire
from subscriptions.models import Subscription
from subscriptions.services import cancel_subscription_immediately


def export_organization_data(organization):
    """
    Export all data for an organization in JSON format (GDPR compliance).

    Args:
        organization: Organization instance

    Returns:
        dict: Complete organization data export
    """
    data = {
        'organization': {
            'name': organization.name,
            'email': organization.email,
            'created_at': organization.created_at.isoformat(),
        },
        'users': [],
        'reviewees': [],
        'questionnaires': [],
        'review_cycles': [],
        'reports': [],
    }

    # Export users
    for profile in UserProfile.objects.for_organization(organization).select_related('user'):
        data['users'].append({
            'username': profile.user.username,
            'email': profile.user.email,
            'is_staff': profile.user.is_staff,
            'can_create_cycles_for_others': profile.can_create_cycles_for_others,
            'created_at': profile.created_at.isoformat(),
        })

    # Export reviewees
    for reviewee in Reviewee.objects.for_organization(organization):
        data['reviewees'].append({
            'name': reviewee.name,
            'email': reviewee.email,
            'department': reviewee.department,
            'is_active': reviewee.is_active,
            'created_at': reviewee.created_at.isoformat(),
        })

    # Export questionnaires
    for questionnaire in Questionnaire.objects.for_organization(organization).prefetch_related('sections__questions'):
        q_data = {
            'name': questionnaire.name,
            'description': questionnaire.description,
            'is_active': questionnaire.is_active,
            'sections': []
        }
        for section in questionnaire.sections.all():
            s_data = {
                'title': section.title,
                'description': section.description,
                'order': section.order,
                'questions': []
            }
            for question in section.questions.all():
                s_data['questions'].append({
                    'question_text': question.question_text,
                    'question_type': question.question_type,
                    'config': question.config,
                    'required': question.required,
                    'order': question.order,
                })
            q_data['sections'].append(s_data)
        data['questionnaires'].append(q_data)

    # Export review cycles
    for cycle in ReviewCycle.objects.for_organization(organization).select_related('reviewee', 'questionnaire'):
        cycle_data = {
            'reviewee': cycle.reviewee.name,
            'questionnaire': cycle.questionnaire.name,
            'status': cycle.status,
            'created_at': cycle.created_at.isoformat(),
            'tokens': [],
            'responses': [],
        }

        # Export tokens (anonymized)
        for token in cycle.tokens.all():
            cycle_data['tokens'].append({
                'category': token.category,
                'invitation_sent_at': token.invitation_sent_at.isoformat() if token.invitation_sent_at else None,
                'completed_at': token.completed_at.isoformat() if token.completed_at else None,
            })

        # Export responses (anonymized - no email/reviewer info)
        for response in cycle.responses.all():
            cycle_data['responses'].append({
                'question_id': response.question.id,
                'category': response.category,
                'answer_data': response.answer_data,
            })

        data['review_cycles'].append(cycle_data)

    # Export reports
    for report in Report.objects.for_organization(organization).select_related('cycle'):
        data['reports'].append({
            'reviewee': report.cycle.reviewee.name,
            'generated_at': report.generated_at.isoformat(),
            'report_data': report.report_data,
        })

    return data


def delete_user_account(user):
    """
    Delete a user account and associated data.

    Args:
        user: User instance to delete

    Returns:
        bool: True if successful
    """
    # Get user profile if exists
    if hasattr(user, 'profile'):
        org = user.profile.organization

        # Check if this is the last admin user in the organization
        admin_count = UserProfile.objects.for_organization(org).filter(
            user__is_staff=True
        ).count()

        if admin_count == 1 and user.is_staff:
            raise ValueError("Cannot delete the last admin user. Delete the organization instead.")

    # Delete user (cascades to profile, tokens, etc.)
    user.delete()

    return True


def delete_organization(organization):
    """
    Delete an organization and all associated data.
    Cancels Stripe subscription if exists.

    Args:
        organization: Organization instance to delete

    Returns:
        bool: True if successful
    """
    # Cancel subscription in Stripe if exists
    try:
        subscription = Subscription.objects.get(organization=organization)
        cancel_subscription_immediately(subscription)
    except Subscription.DoesNotExist:
        pass

    # Delete organization (cascades to all related data)
    # Django cascade will handle:
    # - UserProfile (and users if needed)
    # - Reviewees
    # - Questionnaires
    # - ReviewCycles -> ReviewerTokens -> Responses
    # - Reports
    # - Subscription
    organization.delete()

    return True
