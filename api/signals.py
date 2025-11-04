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
def cycle_saved(sender, instance, created, **kwargs):
    """
    Trigger webhook when cycle is created or completed.
    """
    try:
        if created:
            # Cycle created
            send_webhook(
                organization=instance.reviewee.organization,
                event_type="cycle.created",
                payload={
                    "cycle_id": instance.id,
                    "reviewee": {
                        "id": instance.reviewee.id,
                        "name": instance.reviewee.name,
                        "email": instance.reviewee.email,
                    },
                    "questionnaire": {
                        "id": instance.questionnaire.id,
                        "name": instance.questionnaire.name,
                    },
                    "created_at": instance.created_at.isoformat(),
                },
            )
        elif instance.status == "completed":
            # Check if status just changed to completed
            # We need to check the previous value to avoid duplicate webhooks
            try:
                # Get the instance from DB to compare
                old_instance = ReviewCycle.objects.get(pk=instance.pk)
                if old_instance.status != "completed":
                    # Status just changed to completed
                    send_webhook(
                        organization=instance.reviewee.organization,
                        event_type="cycle.completed",
                        payload={
                            "cycle_id": instance.id,
                            "reviewee": {
                                "id": instance.reviewee.id,
                                "name": instance.reviewee.name,
                                "email": instance.reviewee.email,
                            },
                            "completed_at": instance.updated_at.isoformat(),
                        },
                    )
            except ReviewCycle.DoesNotExist:
                pass  # New instance, ignore
    except Exception as e:
        logger.error(f"Error in cycle_saved webhook: {str(e)}")


@receiver(post_save, sender=Response)
def feedback_submitted(sender, instance, created, **kwargs):
    """
    Trigger webhook when feedback is submitted (token completed).
    """
    try:
        if created:
            # Check if this response completes the token
            token = instance.token
            responses_count = token.responses.count()
            expected_count = instance.cycle.questionnaire.sections.aggregate(
                total=models.Count("questions")
            ).get("total", 0)

            # If all questions answered, mark token as complete
            if responses_count >= expected_count and not token.completed_at:
                from django.utils import timezone

                token.completed_at = timezone.now()
                token.save()

                # Send webhook for completed feedback
                send_webhook(
                    organization=instance.cycle.reviewee.organization,
                    event_type="feedback.submitted",
                    payload={
                        "cycle_id": instance.cycle.id,
                        "category": instance.category,
                        "submitted_at": instance.created_at.isoformat(),
                    },
                )
    except Exception as e:
        logger.error(f"Error in feedback_submitted webhook: {str(e)}")


@receiver(post_save, sender=Report)
def report_generated(sender, instance, created, **kwargs):
    """
    Trigger webhook when report is generated.
    """
    try:
        if created:
            send_webhook(
                organization=instance.cycle.reviewee.organization,
                event_type="report.generated",
                payload={
                    "report_id": instance.id,
                    "cycle_id": instance.cycle.id,
                    "reviewee": {
                        "id": instance.cycle.reviewee.id,
                        "name": instance.cycle.reviewee.name,
                        "email": instance.cycle.reviewee.email,
                    },
                    "generated_at": instance.generated_at.isoformat(),
                    "access_url": f"/reports/view/{instance.access_token}/",
                },
            )
    except Exception as e:
        logger.error(f"Error in report_generated webhook: {str(e)}")
