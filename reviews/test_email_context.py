"""Tests for the facts the reviewer emails state: the time estimate and the response count."""
from itertools import count

from django.test import TestCase
from django.utils import timezone

from accounts.factories import RevieweeFactory
from core.factories import OrganizationFactory
from questionnaires.factories import (
    QuestionnaireFactory, QuestionSectionFactory, RatingQuestionFactory, TextQuestionFactory,
)
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.services import estimated_minutes, responded_count


class EstimatedMinutesTests(TestCase):
    def setUp(self):
        self.questionnaire = QuestionnaireFactory()
        self.section = QuestionSectionFactory(questionnaire=self.questionnaire)

    def test_none_without_questions(self):
        self.assertIsNone(estimated_minutes(self.questionnaire))

    def test_short_questionnaires_round_up_to_whole_minutes(self):
        RatingQuestionFactory.create_batch(7, section=self.section)  # 175 seconds

        self.assertEqual(estimated_minutes(self.questionnaire), 3)

    def test_longer_questionnaires_round_up_to_steps_of_five(self):
        RatingQuestionFactory.create_batch(15, section=self.section)  # 375 seconds
        TextQuestionFactory.create_batch(2, section=self.section)  # 120 seconds

        self.assertEqual(estimated_minutes(self.questionnaire), 10)

    def test_optional_text_questions_add_no_time(self):
        RatingQuestionFactory.create_batch(2, section=self.section)
        TextQuestionFactory.create_batch(3, section=self.section, required=False)

        self.assertEqual(estimated_minutes(self.questionnaire), 1)


class RespondedCountTests(TestCase):
    def setUp(self):
        organization = OrganizationFactory(min_responses_for_anonymity=3)
        self.cycle = ReviewCycleFactory(reviewee=RevieweeFactory(organization=organization))
        self.emails = count()
        self.token = self.reviewer(completed=False)

    def reviewer(self, completed=True, category='peer'):
        return ReviewerTokenFactory(
            cycle=self.cycle, category=category,
            reviewer_email=f'reviewer{next(self.emails)}@acme.example',
            invitation_sent_at=timezone.now(),
            completed_at=timezone.now() if completed else None,
        )

    def test_none_below_the_anonymity_threshold(self):
        self.reviewer()
        self.reviewer()
        self.reviewer(completed=False)

        self.assertIsNone(responded_count(self.token))

    def test_the_count_at_the_threshold(self):
        for _ in range(3):
            self.reviewer()
        self.reviewer(completed=False)

        self.assertEqual(responded_count(self.token), 3)

    def test_none_when_every_other_reviewer_responded(self):
        for _ in range(4):
            self.reviewer()

        self.assertIsNone(responded_count(self.token))

    def test_the_self_assessment_does_not_count(self):
        self.reviewer()
        self.reviewer()
        self.reviewer(category='self')
        self.reviewer(completed=False)

        self.assertIsNone(responded_count(self.token))

    def test_unused_invite_link_tokens_are_not_other_reviewers(self):
        for _ in range(3):
            self.reviewer()
        ReviewerTokenFactory(cycle=self.cycle, category='peer')

        self.assertIsNone(responded_count(self.token))
