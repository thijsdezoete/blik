import uuid
from django.db import models
from core.models import TimeStampedModel
from core.managers import ReportManager
from reviews.models import ReviewCycle


class Report(TimeStampedModel):
    """Generated report for a review cycle"""

    # Public UUID for external references (API, URLs)
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Public identifier for API and URL usage (non-enumerable)"
    )

    cycle = models.OneToOneField(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name='report'
    )

    # Secure access token for reviewee to access their report
    access_token = models.UUIDField(
        unique=True,
        editable=False,
        db_index=True,
        null=True,
        blank=True,
        help_text="Secure token for reviewee access to their report"
    )

    # JSON field for storing aggregated results
    # Structure:
    # {
    #   "by_section": {
    #     "section_id": {
    #       "title": "Leadership",
    #       "questions": {
    #         "question_id": {
    #           "question_text": "...",
    #           "by_category": {
    #             "peer": {"avg": 4.2, "count": 3, "responses": [...]},
    #             "manager": {"avg": 4.5, "count": 1, "responses": [...]}
    #           }
    #         }
    #       }
    #     }
    #   }
    # }
    report_data = models.JSONField()

    generated_at = models.DateTimeField(auto_now_add=True)
    available = models.BooleanField(default=True)

    # Security tracking for report access
    access_token_expires = models.DateTimeField(null=True, blank=True, help_text="Expiration date for access token")
    last_accessed = models.DateTimeField(null=True, blank=True, help_text="Last time report was accessed")
    access_count = models.IntegerField(default=0, help_text="Number of times report has been accessed")

    objects = ReportManager()

    class Meta:
        db_table = 'reports'
        ordering = ['-generated_at']

    def __str__(self):
        return f"Report for {self.cycle}"
