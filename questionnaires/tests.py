from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from core.factories import OrganizationFactory, UserFactory
from accounts.factories import RevieweeFactory, UserProfileFactory
from questionnaires.factories import (
    QuestionnaireFactory,
    QuestionSectionFactory,
    RatingQuestionFactory,
    TextQuestionFactory
)
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.models import ReviewerToken
from reviews.services import send_reviewer_invitations, assign_tokens_to_emails
import uuid


class QuestionnaireTestCase(TestCase):
    """Test questionnaire functionality"""

    def setUp(self):
        self.org = OrganizationFactory(name='Test Organization')
        self.user = UserFactory(username='manager')
        self.user.set_password('testpass123')
        self.user.save()

        self.profile = UserProfileFactory(
            user=self.user,
            organization=self.org
        )

        self.client = Client()
        self.client.force_login(self.user)

        # Create a questionnaire with sections and questions
        self.questionnaire = QuestionnaireFactory(
            organization=self.org,
            name="360 Degree Feedback",
            is_default=True
        )
        self.section = QuestionSectionFactory(
            questionnaire=self.questionnaire,
            title="Technical Skills"
        )
        self.question1 = RatingQuestionFactory(
            section=self.section,
            question_text="Problem solving ability"
        )
        self.question2 = TextQuestionFactory(
            section=self.section,
            question_text="Additional comments"
        )

    def test_questionnaire_created(self):
        """Test that questionnaire is created"""
        self.assertEqual(self.questionnaire.name, "360 Degree Feedback")
        self.assertTrue(self.questionnaire.is_default)
        self.assertTrue(self.questionnaire.is_active)

    def test_questionnaire_has_sections(self):
        """Test that questionnaire has sections"""
        sections = self.questionnaire.sections.all()
        self.assertEqual(sections.count(), 1)
        self.assertEqual(sections.first().title, "Technical Skills")

    def test_section_has_questions(self):
        """Test that section has questions"""
        questions = self.section.questions.all()
        self.assertEqual(questions.count(), 2)

    def test_question_types(self):
        """Test different question types"""
        self.assertEqual(self.question1.question_type, 'rating')
        self.assertEqual(self.question2.question_type, 'text')

    def test_rating_question_config(self):
        """Test rating question configuration"""
        self.assertIn('min', self.question1.config)
        self.assertIn('max', self.question1.config)
        self.assertEqual(self.question1.config['min'], 1)
        self.assertEqual(self.question1.config['max'], 5)


class InviteLinkTestCase(TestCase):
    """Test invite link generation and token functionality"""

    def setUp(self):
        self.org = OrganizationFactory(name='Test Organization')
        self.user = UserFactory(username='manager')

        # Create user profile so SetupMiddleware doesn't redirect
        UserProfileFactory(user=self.user, organization=self.org)

        self.reviewee = RevieweeFactory(
            organization=self.org,
            name='John Developer',
            email='john.dev@test.local'
        )
        self.questionnaire = QuestionnaireFactory(organization=self.org)

        # Create review cycle
        self.cycle = ReviewCycleFactory(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user
        )

        self.client = Client()

    def test_review_cycle_has_invitation_tokens(self):
        """Test that review cycle has invitation tokens"""
        self.assertIsNotNone(self.cycle.invitation_token_self)
        self.assertIsNotNone(self.cycle.invitation_token_peer)
        self.assertIsNotNone(self.cycle.invitation_token_manager)
        self.assertIsNotNone(self.cycle.invitation_token_direct_report)

    def test_invitation_tokens_are_unique(self):
        """Test that all invitation tokens are unique"""
        tokens = [
            self.cycle.invitation_token_self,
            self.cycle.invitation_token_peer,
            self.cycle.invitation_token_manager,
            self.cycle.invitation_token_direct_report
        ]
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_claim_token_creates_reviewer_token(self):
        """Test that claiming an invite creates a reviewer token"""
        # Get count before
        token_count_before = ReviewerToken.objects.filter(
            cycle=self.cycle,
            category='peer'
        ).count()

        # Claim the peer invitation token with force_claim to skip localStorage check
        response = self.client.get(
            reverse('reviews:claim_token', kwargs={
                'invitation_token': self.cycle.invitation_token_peer
            }) + '?force_claim=1'
        )

        # Should redirect to feedback form after creating token
        self.assertEqual(response.status_code, 302)
        # URL pattern: /feedback/<uuid>/
        self.assertIn('/feedback/', response.url)

        # Should create a new reviewer token
        token_count_after = ReviewerToken.objects.filter(
            cycle=self.cycle,
            category='peer'
        ).count()
        self.assertEqual(token_count_after, token_count_before + 1)

    def test_reviewer_token_access(self):
        """Test accessing feedback form with reviewer token"""
        from django.utils import timezone

        # Create a claimed reviewer token (not completed)
        token = ReviewerTokenFactory(
            cycle=self.cycle,
            category='self',
            reviewer_email='john.dev@test.local',
            claimed_at=timezone.now(),  # Mark as claimed
            completed_at=None  # Not yet completed
        )

        response = self.client.get(
            reverse('reviews:feedback_form', kwargs={'token': token.token})
        )

        # Should successfully load feedback form
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.cycle.reviewee.name)


class EmailInviteTestCase(TestCase):
    """Test email invite functionality"""

    def setUp(self):
        self.org = OrganizationFactory(name='Test Organization')
        self.reviewee = RevieweeFactory(organization=self.org)
        self.user = UserFactory()
        self.questionnaire = QuestionnaireFactory(organization=self.org)

        self.cycle = ReviewCycleFactory(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user
        )

    def test_assign_emails_to_tokens(self):
        """Test assigning email addresses to reviewer tokens"""
        # Create peer tokens
        ReviewerTokenFactory(cycle=self.cycle, category='peer')
        ReviewerTokenFactory(cycle=self.cycle, category='peer')

        email_assignments = {
            'peer': ['peer1@test.local', 'peer2@test.local']
        }

        stats = assign_tokens_to_emails(self.cycle, email_assignments)

        self.assertEqual(stats['assigned'], 2)

        # Verify emails were assigned
        peer_tokens_with_email = ReviewerToken.objects.filter(
            cycle=self.cycle,
            category='peer',
            reviewer_email__isnull=False
        )
        self.assertEqual(peer_tokens_with_email.count(), 2)

    def test_send_reviewer_invitations(self):
        """Test sending email invitations to reviewers"""
        # Create token with email
        token = ReviewerTokenFactory(
            cycle=self.cycle,
            category='manager',
            reviewer_email='manager@test.local'
        )

        # Send invitations
        stats = send_reviewer_invitations(self.cycle, token_ids=[token.id])

        # Should send 1 email
        self.assertEqual(stats['sent'], 1)

        # Token should be marked as sent
        token.refresh_from_db()
        self.assertIsNotNone(token.invitation_sent_at)

    def test_dont_resend_completed_invitations(self):
        """Test that completed tokens don't get reinvited"""
        from django.utils import timezone

        token = ReviewerTokenFactory(
            cycle=self.cycle,
            category='peer',
            reviewer_email='peer@test.local',
            completed_at=timezone.now()
        )

        # Try to send invitations (without specifying token_ids)
        stats = send_reviewer_invitations(self.cycle)

        # Should not send to completed token
        self.assertEqual(stats['sent'], 0)
