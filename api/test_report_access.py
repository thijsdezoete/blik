"""Access control for cycles and reports over the API.

The web dashboard and the API are two doors to the same data. Both must apply
the same rule: an org member sees only cycles where they are the reviewee.
Organization scoping alone is not enough — everyone in a small company shares
one organization, and the report detail view hands out `access_token`, which is
an unauthenticated URL to the full report.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Organization, Reviewee, User, UserProfile
from accounts.permissions import assign_organization_admin
from api.models import APIToken
from questionnaires.models import Questionnaire
from reports.services import generate_report
from reviews.models import ReviewCycle


class ReportApiAccessControlTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Test Org')

        self.user1 = User.objects.create_user(
            username='user1', email='user1@example.org', password='pw')
        UserProfile.objects.create(user=self.user1, organization=self.org)

        self.user2 = User.objects.create_user(
            username='user2', email='user2@example.org', password='pw')
        UserProfile.objects.create(user=self.user2, organization=self.org)

        self.admin = User.objects.create_user(
            username='admin', email='admin@example.org', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

        # user1 is the reviewee of a completed cycle with a report.
        reviewee = Reviewee.objects.get(organization=self.org, email='user1@example.org')
        self.cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=Questionnaire.objects.create(
                organization=self.org, name='Q'),
            created_by=self.admin,
            status='completed',
        )
        self.report = generate_report(self.cycle)

        self.client = APIClient()

    def test_member_cannot_list_another_members_report(self):
        self.client.force_login(self.user2)

        response = self.client.get('/api/v1/reports/')

        self.assertEqual(response.status_code, 200)
        uuids = {r['uuid'] for r in response.data['results']}
        self.assertNotIn(str(self.report.uuid), uuids)

    def test_member_cannot_retrieve_another_members_report(self):
        """The detail view exposes access_token — a permanent, login-free URL."""
        self.client.force_login(self.user2)

        response = self.client.get(f'/api/v1/reports/{self.report.uuid}/')

        self.assertEqual(response.status_code, 404)

    def test_member_cannot_list_another_members_cycle(self):
        self.client.force_login(self.user2)

        response = self.client.get('/api/v1/cycles/')

        self.assertEqual(response.status_code, 200)
        uuids = {c['uuid'] for c in response.data['results']}
        self.assertNotIn(str(self.cycle.uuid), uuids)

    def test_reviewee_can_see_own_cycle(self):
        self.client.force_login(self.user1)

        response = self.client.get('/api/v1/cycles/')

        uuids = {c['uuid'] for c in response.data['results']}
        self.assertIn(str(self.cycle.uuid), uuids)

    def test_admin_can_see_all_reports(self):
        self.client.force_login(self.admin)

        response = self.client.get('/api/v1/reports/')

        uuids = {r['uuid'] for r in response.data['results']}
        self.assertIn(str(self.report.uuid), uuids)

    def test_api_token_of_non_admin_creator_cannot_read_others_reports(self):
        """Token auth runs as the token's creator — the same rule must hold."""
        token = APIToken.objects.create(
            organization=self.org, created_by=self.user2, name='User2 Token')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.token}')

        response = self.client.get(f'/api/v1/reports/{self.report.uuid}/')

        self.assertEqual(response.status_code, 404)


    def test_report_data_hides_groups_below_the_organization_threshold(self):
        """The API returns what the web report shows, not the stored raw answers."""
        from questionnaires.models import Question, QuestionSection
        from reviews.models import ReviewerToken, Response
        self.org.min_responses_for_anonymity = 3
        self.org.save()
        section = QuestionSection.objects.create(questionnaire=self.cycle.questionnaire, title='Growth')
        question = Question.objects.create(
            section=section, question_text='Solves problems', question_type='rating',
            config={'min': 1, 'max': 5})
        for category, rating in [('self', 2), ('peer', 4), ('peer', 5)]:
            token = ReviewerToken.objects.create(cycle=self.cycle, category=category)
            Response.objects.create(cycle=self.cycle, question=question, token=token,
                                    category=category, answer_data={'value': rating})
        report = generate_report(self.cycle)
        self.client.force_login(self.user1)

        data = self.client.get(f'/api/v1/reports/{report.uuid}/').data['report_data']

        self.assertTrue(data['section_summary']['Growth']['peer']['insufficient'])
        peer = next(iter(data['by_section'].values()))['questions'][str(question.id)]['by_category']['peer']
        self.assertTrue(peer['insufficient'])
        self.assertNotIn('responses', peer)
