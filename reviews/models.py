import uuid
from django.db import models
from django.contrib.auth.models import User
from core.models import TimeStampedModel
from accounts.models import Reviewee
from questionnaires.models import Questionnaire, Question


class ReviewCycle(TimeStampedModel):
    """360 feedback review cycle for a reviewee"""

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
    ]

    reviewee = models.ForeignKey(
        Reviewee,
        on_delete=models.CASCADE,
        related_name='review_cycles'
    )
    questionnaire = models.ForeignKey(
        Questionnaire,
        on_delete=models.PROTECT,
        related_name='review_cycles'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_review_cycles'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    class Meta:
        db_table = 'review_cycles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reviewee.name} - {self.created_at.strftime('%Y-%m-%d')}"


class ReviewerToken(TimeStampedModel):
    """Anonymous token for reviewer access"""

    CATEGORY_CHOICES = [
        ('self', 'Self Assessment'),
        ('peer', 'Peer Review'),
        ('manager', 'Manager Review'),
        ('direct_report', 'Direct Report Review'),
    ]

    cycle = models.ForeignKey(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name='tokens'
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'reviewer_tokens'
        ordering = ['cycle', 'category']

    def __str__(self):
        return f"{self.cycle} - {self.get_category_display()}"

    @property
    def is_completed(self):
        return self.completed_at is not None


class Response(TimeStampedModel):
    """Individual response to a question"""

    cycle = models.ForeignKey(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name='responses'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='responses'
    )
    token = models.ForeignKey(
        ReviewerToken,
        on_delete=models.CASCADE,
        related_name='responses'
    )
    category = models.CharField(max_length=20)  # Denormalized from token for reporting

    # JSON field for storing answer data
    # For rating: {"value": 4}
    # For text: {"value": "text response"}
    # For multiple_choice: {"value": "Option 1"}
    answer_data = models.JSONField()

    class Meta:
        db_table = 'responses'
        ordering = ['cycle', 'question']
        unique_together = ['token', 'question']

    def __str__(self):
        return f"{self.cycle} - {self.question.question_text[:30]}"
