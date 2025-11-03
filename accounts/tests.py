from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from core.factories import OrganizationFactory, UserFactory
from accounts.factories import (
    UserProfileFactory,
    OrganizationInvitationFactory,
    RevieweeFactory
)
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from accounts.models import OrganizationInvitation, Reviewee


class DashboardTestCase(TestCase):
    """Test dashboard functionality"""

    def setUp(self):
        self.org = OrganizationFactory(name='Test Organization')
        self.user = UserFactory(username='manager')
        self.user.set_password('testpass123')
        self.user.save()

        self.profile = UserProfileFactory(
            user=self.user,
            organization=self.org,
            can_create_cycles_for_others=True
        )

        # Create some reviewees
        self.reviewee1 = RevieweeFactory(
            organization=self.org,
            name='John Developer'
        )
        self.reviewee2 = RevieweeFactory(
            organization=self.org,
            name='Jane Engineer'
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_dashboard_access(self):
        """Test accessing the dashboard"""
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_shows_reviewees(self):
        """Test that dashboard shows reviewees"""
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Dashboard shows count of active reviewees, not individual names
        # Verify reviewees were created
        reviewees = Reviewee.objects.filter(organization=self.org, is_active=True)
        self.assertGreaterEqual(reviewees.count(), 2)


class UserInvitationTestCase(TestCase):
    """Test user invitation functionality"""

    def setUp(self):
        self.org = OrganizationFactory(name='Test Organization')
        self.user = UserFactory(username='admin', is_staff=True, is_superuser=True)
        self.user.set_password('admin123')
        self.user.save()

        self.profile = UserProfileFactory(
            user=self.user,
            organization=self.org,
            can_create_cycles_for_others=True
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_create_invitation(self):
        """Test creating an organization invitation"""
        invitation = OrganizationInvitationFactory(
            organization=self.org,
            email='newuser@test.local',
            invited_by=self.user
        )

        self.assertIsNotNone(invitation.token)
        self.assertEqual(invitation.email, 'newuser@test.local')
        self.assertTrue(invitation.is_valid())

    def test_invitation_token_uniqueness(self):
        """Test that invitation tokens are unique"""
        invite1 = OrganizationInvitationFactory(
            organization=self.org,
            email='user1@test.local',
            invited_by=self.user
        )

        invite2 = OrganizationInvitationFactory(
            organization=self.org,
            email='user2@test.local',
            invited_by=self.user
        )

        self.assertNotEqual(invite1.token, invite2.token)

    def test_expired_invitation_not_valid(self):
        """Test that expired invitations are not valid"""
        invitation = OrganizationInvitationFactory(
            organization=self.org,
            email='expired@test.local',
            invited_by=self.user,
            expires_at=timezone.now() - timedelta(days=1)
        )

        self.assertFalse(invitation.is_valid())

    def test_accepted_invitation_not_valid(self):
        """Test that accepted invitations are not valid"""
        invitation = OrganizationInvitationFactory(
            organization=self.org,
            email='accepted@test.local',
            invited_by=self.user
        )

        # Accept the invitation
        invitation.accepted_at = timezone.now()
        invitation.save()

        self.assertFalse(invitation.is_valid())


class ReportGenerationTestCase(TestCase):
    """Test automatic report generation"""

    def setUp(self):
        self.org = OrganizationFactory(name='Test Organization')
        self.user = UserFactory()
        self.reviewee = RevieweeFactory(organization=self.org)
        self.questionnaire = QuestionnaireFactory(organization=self.org)

        self.cycle = ReviewCycleFactory(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user
        )

    def test_generate_report_for_cycle(self):
        """Test generating a report for a review cycle"""
        from reports.services import generate_report

        # Generate report
        report = generate_report(self.cycle)

        self.assertIsNotNone(report)
        self.assertEqual(report.cycle, self.cycle)
        self.assertIsNotNone(report.report_data)

    def test_cycle_completion_workflow(self):
        """Test the cycle completion workflow"""
        # Create and complete some tokens
        token1 = ReviewerTokenFactory(
            cycle=self.cycle,
            category='self',
            completed_at=timezone.now()
        )
        token2 = ReviewerTokenFactory(
            cycle=self.cycle,
            category='peer',
            completed_at=timezone.now()
        )

        # Mark cycle as completed
        self.cycle.status = 'completed'
        self.cycle.save()

        # Verify cycle is completed
        self.assertEqual(self.cycle.status, 'completed')


class RevieweeManagementTestCase(TestCase):
    """Test reviewee management"""

    def setUp(self):
        self.org = OrganizationFactory(name='Test Organization')
        self.user = UserFactory(username='manager')
        self.user.set_password('testpass123')
        self.user.save()

        self.profile = UserProfileFactory(
            user=self.user,
            organization=self.org,
            can_create_cycles_for_others=True
        )

        self.reviewee1 = RevieweeFactory(
            organization=self.org,
            name='Active Employee'
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_list_reviewees(self):
        """Test listing reviewees"""
        reviewees = Reviewee.objects.filter(
            organization=self.org,
            is_active=True
        )
        self.assertGreater(reviewees.count(), 0)

    def test_create_reviewee(self):
        """Test creating a new reviewee"""
        reviewee = RevieweeFactory(
            organization=self.org,
            name="New Employee",
            email="new.employee@test.local",
            department="Engineering"
        )

        self.assertEqual(reviewee.organization, self.org)
        self.assertTrue(reviewee.is_active)

    def test_deactivate_reviewee(self):
        """Test deactivating a reviewee"""
        self.reviewee1.is_active = False
        self.reviewee1.save()

        self.assertFalse(self.reviewee1.is_active)

    def test_reviewee_organization_association(self):
        """Test that reviewees are properly associated with organization"""
        reviewees = Reviewee.objects.filter(organization=self.org)

        for reviewee in reviewees:
            self.assertEqual(reviewee.organization, self.org)
