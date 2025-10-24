from django.db import models
from core.models import TimeStampedModel, Organization


class Questionnaire(TimeStampedModel):
    """Feedback questionnaire"""
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='questionnaires',
        null=True,  # Allow null for existing records and default questionnaires
        blank=True
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'questionnaires'
        ordering = ['-is_default', 'name']

    def __str__(self):
        return self.name


class QuestionSection(TimeStampedModel):
    """Section grouping questions within a questionnaire"""
    questionnaire = models.ForeignKey(
        Questionnaire,
        on_delete=models.CASCADE,
        related_name='sections'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        db_table = 'question_sections'
        ordering = ['questionnaire', 'order']
        unique_together = ['questionnaire', 'order']

    def __str__(self):
        return f"{self.questionnaire.name} - {self.title}"


class Question(TimeStampedModel):
    """Individual question within a section"""

    QUESTION_TYPES = [
        ('rating', 'Rating Scale'),
        ('likert', 'Likert Scale'),
        ('text', 'Free Text'),
        ('multiple_choice', 'Multiple Choice'),
    ]

    section = models.ForeignKey(
        QuestionSection,
        on_delete=models.CASCADE,
        related_name='questions'
    )
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)

    # JSON field for question configuration
    # For rating: {"min": 1, "max": 5, "labels": {"1": "Poor", "5": "Excellent"}}
    # For likert: {"scale": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]}
    # For multiple_choice: {"choices": ["Option 1", "Option 2"]}
    config = models.JSONField(default=dict)

    required = models.BooleanField(default=True)
    order = models.IntegerField(default=0)

    class Meta:
        db_table = 'questions'
        ordering = ['section', 'order']
        unique_together = ['section', 'order']

    def __str__(self):
        return f"{self.section.title} - {self.question_text[:50]}"
