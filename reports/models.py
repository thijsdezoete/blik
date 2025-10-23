from django.db import models
from core.models import TimeStampedModel
from reviews.models import ReviewCycle


class Report(TimeStampedModel):
    """Generated report for a review cycle"""

    cycle = models.OneToOneField(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name='report'
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

    class Meta:
        db_table = 'reports'
        ordering = ['-generated_at']

    def __str__(self):
        return f"Report for {self.cycle}"
