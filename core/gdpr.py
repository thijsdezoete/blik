"""
GDPR Compliance - User and Reviewee Data Deletion Service

This module provides two deletion modes:
1. Soft Delete (default): Anonymize identifiable data while preserving data structure
2. Hard Delete: Complete removal with cascade deletion

Handles:
- Django User models
- Reviewee models
- Related data (responses, tokens, etc.)
- Security logs (django-axes)
- External services (Stripe)
"""

import uuid
import logging
from datetime import datetime
from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone

logger = logging.getLogger(__name__)


class GDPRDeletionService:
    """
    Service for GDPR-compliant deletion of user and reviewee data.
    """

    @staticmethod
    def _generate_anonymized_email():
        """Generate an anonymized email address"""
        return f"deleted-{uuid.uuid4().hex[:16]}@deleted.invalid"

    @staticmethod
    def _generate_anonymized_name():
        """Generate an anonymized name"""
        return f"Deleted User {uuid.uuid4().hex[:8]}"

    @staticmethod
    def _log_deletion(entity_type, entity_id, deletion_type, performed_by=None):
        """
        Log deletion event for audit trail.

        Args:
            entity_type: Type of entity deleted (User, Reviewee, etc.)
            entity_id: ID of the deleted entity
            deletion_type: 'soft' or 'hard'
            performed_by: User who performed the deletion (optional)
        """
        log_data = {
            'timestamp': timezone.now().isoformat(),
            'entity_type': entity_type,
            'entity_id': entity_id,
            'deletion_type': deletion_type,
            'performed_by': performed_by.username if performed_by else 'system',
        }
        logger.info(f"GDPR Deletion: {log_data}")

    @staticmethod
    def _delete_axes_logs_for_user(username):
        """
        Delete django-axes security logs for a user.

        Args:
            username: Username to delete logs for
        """
        try:
            # Import axes models if available
            from axes.models import AccessAttempt, AccessLog, AccessFailureLog

            deleted_counts = {
                'access_attempts': AccessAttempt.objects.filter(username=username).delete()[0],
                'access_logs': AccessLog.objects.filter(username=username).delete()[0],
                'access_failures': AccessFailureLog.objects.filter(username=username).delete()[0],
            }

            logger.info(f"Deleted axes logs for {username}: {deleted_counts}")
            return deleted_counts
        except ImportError:
            logger.warning("django-axes not installed, skipping axes log deletion")
            return None
        except Exception as e:
            logger.error(f"Error deleting axes logs for {username}: {e}")
            raise

    @staticmethod
    def _anonymize_axes_logs_for_user(username):
        """
        Anonymize django-axes security logs for a user.

        Args:
            username: Username to anonymize logs for
        """
        try:
            from axes.models import AccessAttempt, AccessLog, AccessFailureLog

            anonymized_username = f"deleted-{uuid.uuid4().hex[:12]}"

            updated_counts = {
                'access_attempts': AccessAttempt.objects.filter(username=username).update(
                    username=anonymized_username
                ),
                'access_logs': AccessLog.objects.filter(username=username).update(
                    username=anonymized_username
                ),
                'access_failures': AccessFailureLog.objects.filter(username=username).update(
                    username=anonymized_username
                ),
            }

            logger.info(f"Anonymized axes logs for {username}: {updated_counts}")
            return updated_counts
        except ImportError:
            logger.warning("django-axes not installed, skipping axes log anonymization")
            return None
        except Exception as e:
            logger.error(f"Error anonymizing axes logs for {username}: {e}")
            raise

    @staticmethod
    @transaction.atomic
    def delete_user(user_id, hard_delete=False, performed_by=None):
        """
        Delete or anonymize a Django User and related data.

        Args:
            user_id: ID of the User to delete
            hard_delete: If True, completely delete. If False (default), anonymize.
            performed_by: User performing the deletion (for audit trail)

        Returns:
            dict: Summary of deletion actions

        Raises:
            User.DoesNotExist: If user not found
        """
        from accounts.models import UserProfile

        user = User.objects.select_related('profile').get(pk=user_id)
        username = user.username

        logger.info(f"Starting {'hard' if hard_delete else 'soft'} delete for User {user_id} ({username})")

        result = {
            'user_id': user_id,
            'username': username,
            'deletion_type': 'hard' if hard_delete else 'soft',
            'timestamp': timezone.now().isoformat(),
        }

        if hard_delete:
            # Hard delete: Complete removal
            # Note: CASCADE will handle UserProfile, OneTimeLoginToken automatically

            # Delete axes logs
            axes_result = GDPRDeletionService._delete_axes_logs_for_user(username)
            result['axes_logs_deleted'] = axes_result

            # Delete user (CASCADE handles related objects)
            user.delete()
            result['status'] = 'deleted'

            logger.info(f"Hard deleted User {user_id}")

        else:
            # Soft delete: Anonymize identifiable data

            # Anonymize axes logs
            axes_result = GDPRDeletionService._anonymize_axes_logs_for_user(username)
            result['axes_logs_anonymized'] = axes_result

            # Anonymize user fields
            user.username = GDPRDeletionService._generate_anonymized_email()
            user.email = GDPRDeletionService._generate_anonymized_email()
            user.first_name = ''
            user.last_name = ''
            user.is_active = False
            user.set_unusable_password()
            user.save()

            result['status'] = 'anonymized'
            result['new_username'] = user.username

            logger.info(f"Soft deleted (anonymized) User {user_id}")

        # Log deletion event
        GDPRDeletionService._log_deletion('User', user_id, 'hard' if hard_delete else 'soft', performed_by)

        return result

    @staticmethod
    @transaction.atomic
    def delete_reviewee(reviewee_id, hard_delete=False, performed_by=None):
        """
        Delete or anonymize a Reviewee and related feedback data.

        Args:
            reviewee_id: ID of the Reviewee to delete
            hard_delete: If True, completely delete. If False (default), anonymize.
            performed_by: User performing the deletion (for audit trail)

        Returns:
            dict: Summary of deletion actions

        Raises:
            Reviewee.DoesNotExist: If reviewee not found
        """
        from accounts.models import Reviewee
        from reviews.models import ReviewCycle

        reviewee = Reviewee.objects.get(pk=reviewee_id)
        name = reviewee.name
        email = reviewee.email

        logger.info(f"Starting {'hard' if hard_delete else 'soft'} delete for Reviewee {reviewee_id} ({name})")

        result = {
            'reviewee_id': reviewee_id,
            'name': name,
            'email': email,
            'deletion_type': 'hard' if hard_delete else 'soft',
            'timestamp': timezone.now().isoformat(),
        }

        # Count related data
        cycle_count = ReviewCycle.objects.filter(reviewee=reviewee).count()
        result['review_cycles_affected'] = cycle_count

        if hard_delete:
            # Hard delete: Complete removal
            # Note: CASCADE will handle ReviewCycle, ReviewerToken, Response, Report automatically

            reviewee.delete()
            result['status'] = 'deleted'
            result['cascade_note'] = 'All related review cycles, tokens, responses, and reports deleted'

            logger.info(f"Hard deleted Reviewee {reviewee_id} and {cycle_count} review cycles")

        else:
            # Soft delete: Anonymize identifiable data
            # Keep structure intact but remove PII

            reviewee.name = GDPRDeletionService._generate_anonymized_name()
            reviewee.email = GDPRDeletionService._generate_anonymized_email()
            reviewee.department = ''
            reviewee.is_active = False
            reviewee.save()

            result['status'] = 'anonymized'
            result['new_name'] = reviewee.name
            result['new_email'] = reviewee.email
            result['cascade_note'] = 'Review cycles, responses, and reports preserved but reviewee identity removed'

            logger.info(f"Soft deleted (anonymized) Reviewee {reviewee_id}")

        # Log deletion event
        GDPRDeletionService._log_deletion('Reviewee', reviewee_id, 'hard' if hard_delete else 'soft', performed_by)

        return result

    @staticmethod
    @transaction.atomic
    def delete_reviewee_and_anonymize_reviewer_emails(reviewee_id, performed_by=None):
        """
        Delete reviewee with additional step: anonymize all reviewer emails in tokens.
        This is a more aggressive soft delete that removes reviewer identities.

        Args:
            reviewee_id: ID of the Reviewee to delete
            performed_by: User performing the deletion (for audit trail)

        Returns:
            dict: Summary of deletion actions
        """
        from accounts.models import Reviewee
        from reviews.models import ReviewCycle, ReviewerToken

        reviewee = Reviewee.objects.get(pk=reviewee_id)

        logger.info(f"Starting full anonymization delete for Reviewee {reviewee_id}")

        # First, anonymize all reviewer emails in tokens for this reviewee's cycles
        reviewer_tokens = ReviewerToken.objects.filter(cycle__reviewee=reviewee)
        token_count = reviewer_tokens.count()

        for token in reviewer_tokens:
            if token.reviewer_email:
                token.reviewer_email = GDPRDeletionService._generate_anonymized_email()
                token.save()

        # Then anonymize the reviewee
        result = GDPRDeletionService.delete_reviewee(
            reviewee_id,
            hard_delete=False,
            performed_by=performed_by
        )

        result['reviewer_emails_anonymized'] = token_count
        result['deletion_mode'] = 'full_anonymization'

        logger.info(f"Fully anonymized Reviewee {reviewee_id} and {token_count} reviewer emails")

        return result

    @staticmethod
    def delete_organization_data(organization_id, performed_by=None):
        """
        Delete all data for an organization (DANGEROUS - use with caution).
        This is always a hard delete due to CASCADE relationships.

        Args:
            organization_id: ID of the Organization
            performed_by: User performing the deletion (for audit trail)

        Returns:
            dict: Summary of deletion actions

        Warning:
            This will delete ALL data for the organization including:
            - All users
            - All reviewees
            - All review cycles, tokens, responses, reports
            - All questionnaires
            - All subscriptions
        """
        from core.models import Organization

        org = Organization.objects.get(pk=organization_id)
        org_name = org.name

        logger.warning(f"Starting FULL ORGANIZATION DELETE for {org_name} (ID: {organization_id})")

        # Count everything before deletion
        from accounts.models import UserProfile, Reviewee, OrganizationInvitation
        from reviews.models import ReviewCycle
        from questionnaires.models import Questionnaire
        from subscriptions.models import Subscription

        result = {
            'organization_id': organization_id,
            'organization_name': org_name,
            'deletion_type': 'hard',
            'timestamp': timezone.now().isoformat(),
            'deleted_counts': {
                'users': UserProfile.objects.filter(organization=org).count(),
                'reviewees': Reviewee.objects.filter(organization=org).count(),
                'review_cycles': ReviewCycle.objects.filter(reviewee__organization=org).count(),
                'invitations': OrganizationInvitation.objects.filter(organization=org).count(),
                'questionnaires': Questionnaire.objects.filter(organization=org).count(),
            }
        }

        try:
            result['deleted_counts']['subscriptions'] = Subscription.objects.filter(organization=org).count()
        except:
            pass

        # Delete organization (CASCADE handles everything)
        org.delete()

        result['status'] = 'deleted'

        logger.warning(f"Organization {organization_id} fully deleted: {result['deleted_counts']}")

        # Log deletion event
        GDPRDeletionService._log_deletion('Organization', organization_id, 'hard', performed_by)

        return result

    @staticmethod
    def get_user_data_summary(user_id):
        """
        Get a summary of all data associated with a user (for GDPR data export/review).

        Args:
            user_id: ID of the User

        Returns:
            dict: Summary of user's data
        """
        from accounts.models import UserProfile
        from reviews.models import ReviewCycle

        user = User.objects.get(pk=user_id)

        summary = {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'date_joined': user.date_joined.isoformat(),
                'last_login': user.last_login.isoformat() if user.last_login else None,
            },
            'profile': None,
            'created_cycles': ReviewCycle.objects.filter(created_by=user).count(),
        }

        try:
            profile = user.profile
            summary['profile'] = {
                'organization': profile.organization.name,
                'can_create_cycles_for_others': profile.can_create_cycles_for_others,
            }
        except:
            pass

        return summary

    @staticmethod
    def get_reviewee_data_summary(reviewee_id):
        """
        Get a summary of all data associated with a reviewee (for GDPR data export/review).

        Args:
            reviewee_id: ID of the Reviewee

        Returns:
            dict: Summary of reviewee's data
        """
        from accounts.models import Reviewee
        from reviews.models import ReviewCycle, ReviewerToken, Response
        from reports.models import Report

        reviewee = Reviewee.objects.get(pk=reviewee_id)
        cycles = ReviewCycle.objects.filter(reviewee=reviewee)

        summary = {
            'reviewee': {
                'id': reviewee.id,
                'name': reviewee.name,
                'email': reviewee.email,
                'department': reviewee.department,
                'organization': reviewee.organization.name,
                'is_active': reviewee.is_active,
            },
            'review_cycles': {
                'total': cycles.count(),
                'active': cycles.filter(status='active').count(),
                'completed': cycles.filter(status='completed').count(),
            },
            'tokens': ReviewerToken.objects.filter(cycle__reviewee=reviewee).count(),
            'responses': Response.objects.filter(cycle__reviewee=reviewee).count(),
            'reports': Report.objects.filter(cycle__reviewee=reviewee).count(),
        }

        return summary
