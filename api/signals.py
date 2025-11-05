"""
Signal handlers for triggering webhooks on model events.
"""
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from reviews.models import ReviewCycle, Response
from reports.models import Report
from .webhooks import send_webhook
import logging

logger = logging.getLogger("api")


@receiver(post_save, sender=ReviewCycle)
def cycle_saved(sender, instance, created, update_fields, **kwargs):
    """
    Trigger webhook when cycle is created or completed.
    """
    try:
        if created:
            # Cycle created - schedule webhook to fire after transaction commits
            # This ensures any ReviewerTokens created in the same transaction are visible
            from django.db import transaction

            def send_cycle_created_webhook():
                # Refresh to get latest state including any tokens
                from django.db.models import Count, Q
                cycle = ReviewCycle.objects.get(pk=instance.pk)

                reviewer_stats = cycle.tokens.values('category').annotate(
                    total=Count('id'),
                    invited=Count('id', filter=Q(invitation_sent_at__isnull=False))
                )

                # Build reviewer summary dict
                reviewers = {}
                for stat in reviewer_stats:
                    category = stat['category']
                    reviewers[category] = {
                        "invited": stat['invited'],
                        "total": stat['total']
                    }

                send_webhook(
                    organization=cycle.reviewee.organization,
                    event_type="cycle.created",
                    payload={
                        "cycle_id": str(cycle.uuid),
                        "reviewee": {
                            "id": str(cycle.reviewee.uuid),
                            "name": cycle.reviewee.name,
                            "email": cycle.reviewee.email,
                        },
                        "questionnaire": {
                            "id": cycle.questionnaire.id,
                            "name": cycle.questionnaire.name,
                        },
                        "reviewers": reviewers,
                        "created_at": cycle.created_at.isoformat(),
                    },
                )

            transaction.on_commit(send_cycle_created_webhook)

        elif instance.status == "completed" and not created:
            # Check if status field was just updated
            # If update_fields is None, all fields were potentially updated
            # If update_fields contains 'status', the status was explicitly changed
            if update_fields is None or 'status' in update_fields:
                send_webhook(
                    organization=instance.reviewee.organization,
                    event_type="cycle.completed",
                    payload={
                        "cycle_id": str(instance.uuid),
                        "reviewee": {
                            "id": str(instance.reviewee.uuid),
                            "name": instance.reviewee.name,
                            "email": instance.reviewee.email,
                        },
                        "completed_at": instance.updated_at.isoformat(),
                    },
                )
    except Exception as e:
        logger.error(f"Error in cycle_saved webhook: {str(e)}")


# Note: feedback.submitted webhook is now handled directly in reviews/views.py
# after the token is marked as completed, to avoid race conditions with
# multiple Response objects being created in a loop.


@receiver(post_save, sender=Report)
def report_generated(sender, instance, created, update_fields, **kwargs):
    """
    Trigger webhook when report is generated or regenerated.
    """
    try:
        # Fire webhook when:
        # 1. Report is newly created, OR
        # 2. Report is updated via update_or_create (update_fields will be None), OR
        # 3. Report's report_data field is explicitly updated
        #
        # Skip if only access_token is being set (update_fields=['access_token'])
        should_fire = (
            created or
            update_fields is None or
            (update_fields and 'report_data' in update_fields)
        )

        logger.info(f"Report saved: created={created}, update_fields={update_fields}, "
                   f"should_fire={should_fire}, available={instance.available}, "
                   f"has_token={bool(instance.access_token)}")

        # Also ensure the report is ready (has access_token and is available)
        if should_fire and instance.available and instance.access_token:
            logger.info(f"Sending report.generated webhook for report {instance.id}")
            send_webhook(
                organization=instance.cycle.reviewee.organization,
                event_type="report.generated",
                payload={
                    "report_id": str(instance.uuid),
                    "cycle_id": str(instance.cycle.uuid),
                    "reviewee": {
                        "id": str(instance.cycle.reviewee.uuid),
                        "name": instance.cycle.reviewee.name,
                        "email": instance.cycle.reviewee.email,
                    },
                    "generated_at": instance.generated_at.isoformat(),
                    "access_url": f"/reports/view/{instance.access_token}/",
                },
            )
        else:
            logger.warning(f"Report webhook NOT sent - should_fire={should_fire}, "
                         f"available={instance.available}, has_token={bool(instance.access_token)}")
    except Exception as e:
        logger.error(f"Error in report_generated webhook: {str(e)}")
