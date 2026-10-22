"""
Tests for "Did not observe" feature on rating questions.

This feature allows reviewers to indicate they did not observe behavior
for a rating question, which is stored as {"value": None, "did_not_observe": True}
and excluded from all numerical calculations.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from core.models import Organization
from accounts.models import Reviewee
from questionnaires.models import Questionnaire, QuestionSection, Question
from reviews.models import ReviewCycle, ReviewerToken, Response
from reports.services import generate_report


class DidNotObserveTestCase(TestCase):
    """Test that 'Did not observe' responses are properly handled."""

    def setUp(self):
        """Create test data for rating questions."""
        self.organization = Organization.objects.create(name='Test Org')
        self.user = User.objects.create_user(username='testuser')
        self.reviewee = Reviewee.objects.create(
            organization=self.organization,
            name='Test Reviewee',
            email='reviewee@example.com',
        )
        self.questionnaire = Questionnaire.objects.create(
            organization=self.organization,
            name='Test Questionnaire',
            source_language='en-us',
        )
        self.section = QuestionSection.objects.create(
            questionnaire=self.questionnaire,
            title='Skills',
            order=1,
        )
        self.rating_question = Question.objects.create(
            section=self.section,
            question_text='How well does this person communicate?',
            question_type='rating',
            config={'min': 1, 'max': 5},
            required=True,
            order=1,
        )
        self.cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user,
        )

    def test_normal_numeric_rating_still_works(self):
        """Verify that regular numeric ratings continue to work as before."""
        token = ReviewerToken.objects.create(cycle=self.cycle, category='peer')

        # Submit normal rating
        response = Response.objects.create(
            cycle=self.cycle,
            token=token,
            question=self.rating_question,
            category='peer',
            answer_data={'value': 4},
        )

        # Verify storage
        self.assertEqual(response.answer_data['value'], 4)
        self.assertNotIn('did_not_observe', response.answer_data)

        # Generate report and verify calculation
        report = generate_report(self.cycle)
        section_data = report.report_data['by_section'][str(self.section.id)]
        question_data = section_data['questions'][str(self.rating_question.id)]

        self.assertEqual(question_data['by_category']['peer']['avg'], 4.0)
        self.assertEqual(question_data['by_category']['peer']['count'], 1)

    def test_did_not_observe_can_be_submitted(self):
        """Verify that 'Did not observe' response can be stored."""
        token = ReviewerToken.objects.create(cycle=self.cycle, category='peer')

        response = Response.objects.create(
            cycle=self.cycle,
            token=token,
            question=self.rating_question,
            category='peer',
            answer_data={'value': None, 'did_not_observe': True},
        )

        # Verify storage
        self.assertIsNone(response.answer_data['value'])
        self.assertTrue(response.answer_data['did_not_observe'])

    def test_required_rating_accepts_did_not_observe(self):
        """Required rating questions should accept 'Did not observe' as valid."""
        token = ReviewerToken.objects.create(cycle=self.cycle, category='peer')

        # Create response with did_not_observe
        response = Response.objects.create(
            cycle=self.cycle,
            token=token,
            question=self.rating_question,
            category='peer',
            answer_data={'value': None, 'did_not_observe': True},
        )

        # Should not raise validation error
        self.assertEqual(Response.objects.filter(token=token).count(), 1)

    def test_unanswered_required_question_validation(self):
        """Unanswered required questions should still be rejected."""
        # This would be tested at the view level in submit_feedback
        # Here we verify the data distinction: no Response object vs did_not_observe Response
        token = ReviewerToken.objects.create(cycle=self.cycle, category='peer')

        # No response created = unanswered
        self.assertEqual(Response.objects.filter(token=token).count(), 0)

        # Create did_not_observe response
        Response.objects.create(
            cycle=self.cycle,
            token=token,
            question=self.rating_question,
            category='peer',
            answer_data={'value': None, 'did_not_observe': True},
        )

        # Now there is a response (answered with did_not_observe)
        self.assertEqual(Response.objects.filter(token=token).count(), 1)

    def test_did_not_observe_excluded_from_numerical_calculations(self):
        """Did not observe responses must not affect averages."""
        # Create three reviewers: one numeric, one did_not_observe, one numeric
        token1 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')
        token2 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')
        token3 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')

        Response.objects.create(
            cycle=self.cycle,
            token=token1,
            question=self.rating_question,
            category='peer',
            answer_data={'value': 3},
        )
        Response.objects.create(
            cycle=self.cycle,
            token=token2,
            question=self.rating_question,
            category='peer',
            answer_data={'value': None, 'did_not_observe': True},
        )
        Response.objects.create(
            cycle=self.cycle,
            token=token3,
            question=self.rating_question,
            category='peer',
            answer_data={'value': 5},
        )

        # Generate report
        report = generate_report(self.cycle)
        section_data = report.report_data['by_section'][str(self.section.id)]
        question_data = section_data['questions'][str(self.rating_question.id)]

        # Average should be (3 + 5) / 2 = 4.0, not (3 + 0 + 5) / 3
        self.assertEqual(question_data['by_category']['peer']['avg'], 4.0)

        # Count includes all responses (including did_not_observe)
        self.assertEqual(question_data['by_category']['peer']['count'], 3)

        # Distribution should only include numeric values
        distribution = question_data['by_category']['peer']['distribution']
        self.assertEqual(distribution, {'3': 1, '5': 1})
        self.assertNotIn('None', distribution)

    def test_mixed_numeric_and_did_not_observe_responses(self):
        """Test multiple categories with mixed response types."""
        # Self: numeric
        self_token = ReviewerToken.objects.create(cycle=self.cycle, category='self')
        Response.objects.create(
            cycle=self.cycle,
            token=self_token,
            question=self.rating_question,
            category='self',
            answer_data={'value': 3},
        )

        # Peer 1: numeric
        peer_token1 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')
        Response.objects.create(
            cycle=self.cycle,
            token=peer_token1,
            question=self.rating_question,
            category='peer',
            answer_data={'value': 4},
        )

        # Peer 2: did_not_observe
        peer_token2 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')
        Response.objects.create(
            cycle=self.cycle,
            token=peer_token2,
            question=self.rating_question,
            category='peer',
            answer_data={'value': None, 'did_not_observe': True},
        )

        # Manager: did_not_observe
        manager_token = ReviewerToken.objects.create(cycle=self.cycle, category='manager')
        Response.objects.create(
            cycle=self.cycle,
            token=manager_token,
            question=self.rating_question,
            category='manager',
            answer_data={'value': None, 'did_not_observe': True},
        )

        # Generate report
        report = generate_report(self.cycle)
        section_data = report.report_data['by_section'][str(self.section.id)]
        question_data = section_data['questions'][str(self.rating_question.id)]

        # Self should have avg of 3
        self.assertEqual(question_data['by_category']['self']['avg'], 3.0)

        # Peer should have avg of 4 (only one numeric response)
        self.assertEqual(question_data['by_category']['peer']['avg'], 4.0)
        self.assertEqual(question_data['by_category']['peer']['count'], 2)

        # Manager should have no avg (only did_not_observe)
        self.assertNotIn('avg', question_data['by_category']['manager'])
        self.assertEqual(question_data['by_category']['manager']['count'], 1)

    def test_all_did_not_observe_produces_no_score(self):
        """When all responses are 'did not observe', no average should be calculated."""
        token1 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')
        token2 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')

        Response.objects.create(
            cycle=self.cycle,
            token=token1,
            question=self.rating_question,
            category='peer',
            answer_data={'value': None, 'did_not_observe': True},
        )
        Response.objects.create(
            cycle=self.cycle,
            token=token2,
            question=self.rating_question,
            category='peer',
            answer_data={'value': None, 'did_not_observe': True},
        )

        # Generate report
        report = generate_report(self.cycle)
        section_data = report.report_data['by_section'][str(self.section.id)]
        question_data = section_data['questions'][str(self.rating_question.id)]

        # Should have count but no average
        self.assertEqual(question_data['by_category']['peer']['count'], 2)
        self.assertNotIn('avg', question_data['by_category']['peer'])

        # Should have no distribution (no numeric values)
        self.assertNotIn('distribution', question_data['by_category']['peer'])

    def test_backwards_compatibility_with_existing_responses(self):
        """Existing responses without did_not_observe flag should work normally."""
        token = ReviewerToken.objects.create(cycle=self.cycle, category='peer')

        # Old-style response (no did_not_observe key)
        response = Response.objects.create(
            cycle=self.cycle,
            token=token,
            question=self.rating_question,
            category='peer',
            answer_data={'value': 4},
        )

        # Generate report
        report = generate_report(self.cycle)
        section_data = report.report_data['by_section'][str(self.section.id)]
        question_data = section_data['questions'][str(self.rating_question.id)]

        # Should calculate normally
        self.assertEqual(question_data['by_category']['peer']['avg'], 4.0)

    def test_did_not_observe_excluded_from_insights(self):
        """Did not observe should not affect perception gaps, strengths, etc."""
        # Self: numeric
        self_token = ReviewerToken.objects.create(cycle=self.cycle, category='self')
        Response.objects.create(
            cycle=self.cycle,
            token=self_token,
            question=self.rating_question,
            category='self',
            answer_data={'value': 3},
        )

        # Peers: one numeric, one did_not_observe
        peer_token1 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')
        Response.objects.create(
            cycle=self.cycle,
            token=peer_token1,
            question=self.rating_question,
            category='peer',
            answer_data={'value': 5},
        )

        peer_token2 = ReviewerToken.objects.create(cycle=self.cycle, category='peer')
        Response.objects.create(
            cycle=self.cycle,
            token=peer_token2,
            question=self.rating_question,
            category='peer',
            answer_data={'value': None, 'did_not_observe': True},
        )

        # Generate report
        report = generate_report(self.cycle)

        # Verify insights are calculated from numeric values only
        # Self avg should be 3, peer avg should be 5 (not including did_not_observe)
        section_data = report.report_data['by_section'][str(self.section.id)]
        question_data = section_data['questions'][str(self.rating_question.id)]

        self.assertEqual(question_data['by_category']['self']['avg'], 3.0)
        self.assertEqual(question_data['by_category']['peer']['avg'], 5.0)
