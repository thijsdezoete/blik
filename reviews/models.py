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

    @property
    def organization(self):
        """Get organization through reviewee relationship"""
        return self.reviewee.organization

    # Secure invitation tokens per category (non-enumerable)
    invitation_token_self = models.UUIDField(unique=True, db_index=True, null=True, blank=True)
    invitation_token_peer = models.UUIDField(unique=True, db_index=True, null=True, blank=True)
    invitation_token_manager = models.UUIDField(unique=True, db_index=True, null=True, blank=True)
    invitation_token_direct_report = models.UUIDField(unique=True, db_index=True, null=True, blank=True)

    class Meta:
        db_table = 'review_cycles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reviewee.name} - {self.created_at.strftime('%Y-%m-%d')}"

    def save(self, *args, **kwargs):
        """Auto-generate invitation tokens for all categories on creation"""
        if not self.pk:  # New instance
            if not self.invitation_token_self:
                self.invitation_token_self = uuid.uuid4()
            if not self.invitation_token_peer:
                self.invitation_token_peer = uuid.uuid4()
            if not self.invitation_token_manager:
                self.invitation_token_manager = uuid.uuid4()
            if not self.invitation_token_direct_report:
                self.invitation_token_direct_report = uuid.uuid4()
        super().save(*args, **kwargs)

    def get_invitation_token(self, category):
        """Get the invitation token for a specific category"""
        token_map = {
            'self': self.invitation_token_self,
            'peer': self.invitation_token_peer,
            'manager': self.invitation_token_manager,
            'direct_report': self.invitation_token_direct_report,
        }
        return token_map.get(category)


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
    reviewer_email = models.EmailField(
        null=True,
        blank=True,
        help_text="Email to send invitation to (not stored with responses for anonymity)"
    )
    invitation_sent_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When someone claimed this token by clicking the invitation link"
    )
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
