from django.test import TestCase
from django.urls import reverse

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory, UserProfileFactory
from accounts.models import ReviewSetup, Reviewee
from accounts.permissions import assign_organization_admin, assign_organization_member, set_user_permission
from core.factories import OrganizationFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle, ReviewerToken
from reviews.setup import save_review_setup
from subscriptions.testing import grant


class RevieweeDetailTests(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.user = self.profile.user
        self.org = self.profile.organization
        assign_organization_admin(self.user)
        self.client.force_login(self.user)
        self.questionnaire = QuestionnaireFactory(organization=self.org, is_default=True)
        self.alex = RevieweeFactory(organization=self.org, name='Alex Morgan', email='alex@acme.example',
                                    department='Product Engineering')
        self.blair = RevieweeFactory(organization=self.org, name='Blair Chen', email='blair@acme.example')
        self.url = reverse('reviewee_detail', args=[self.alex.uuid])

    def post(self, action, **fields):
        return self.client.post(self.url, {
            'action': action, 'questionnaire': self.questionnaire.id, 'categories_submitted': '1',
            'include_self': 'on', 'include_manager': 'on', 'include_peer': 'on', **fields,
        })

    def rows(self):
        return sorted(ReviewSetup.objects.get(reviewee=self.alex).reviewers.values_list(
            'category', 'person', 'email'), key=str)

    def member(self, email=None):
        profile = UserProfileFactory(organization=self.org, **({'user__email': email} if email else {}))
        assign_organization_member(profile.user)
        return profile.user

    def make_manager_of_alex(self, user):
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=Reviewee.objects.get(email=user.email), row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.alex, row=1, col=0)

    def test_save_stores_the_posted_list(self):
        response = self.post('save', manager_reviewees=[str(self.blair.uuid)], peer_emails='dana@acme.example')

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        saved = ReviewSetup.objects.get(reviewee=self.alex)
        self.assertEqual(saved.questionnaire, self.questionnaire)
        self.assertEqual(
            (saved.include_self, saved.include_manager, saved.include_peer, saved.include_direct_report),
            (True, True, True, False))
        self.assertEqual(self.rows(), sorted([('manager', self.blair.pk, ''), ('peer', None, 'dana@acme.example')], key=str))
        self.assertFalse(ReviewCycle.objects.exists())

    def test_start_creates_a_cycle_with_one_token_per_reviewer_and_saves_the_list(self):
        response = self.post('start', manager_reviewees=[str(self.blair.uuid)], peer_emails='dana@acme.example')

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        cycle = ReviewCycle.objects.get(reviewee=self.alex)
        self.assertEqual(cycle.questionnaire, self.questionnaire)
        self.assertEqual(
            sorted(cycle.tokens.values_list('category', 'reviewer_email')),
            [('manager', 'blair@acme.example'), ('peer', 'dana@acme.example'), ('self', 'alex@acme.example')])
        self.assertFalse(any(f.related_model is Reviewee for f in ReviewerToken._meta.fields))
        self.assertEqual(self.rows(), sorted([('manager', self.blair.pk, ''), ('peer', None, 'dana@acme.example')], key=str))

    def test_start_without_credits_creates_nothing(self):
        grant(self.org, 0)

        self.post('start', manager_reviewees=[str(self.blair.uuid)])

        self.assertFalse(ReviewCycle.objects.exists())
        self.assertFalse(ReviewerToken.objects.exists())
        self.assertEqual(self.rows(), [('manager', self.blair.pk, '')])

    def test_unselected_category_gets_no_tokens(self):
        self.client.post(self.url, {
            'action': 'start', 'questionnaire': self.questionnaire.id, 'categories_submitted': '1',
            'include_self': 'on', 'include_manager': 'on',
            'manager_reviewees': [str(self.blair.uuid)], 'peer_emails': 'dana@acme.example',
        })

        cycle = ReviewCycle.objects.get(reviewee=self.alex)
        self.assertFalse(cycle.tokens.filter(category='peer').exists())
        saved = ReviewSetup.objects.get(reviewee=self.alex)
        self.assertFalse(saved.include_peer)
        self.assertIn(('peer', None, 'dana@acme.example'), self.rows())

    def test_colleague_gets_a_404(self):
        self.client.force_login(self.member())

        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.post('save', peer_emails='dana@acme.example').status_code, 404)
        self.assertFalse(ReviewSetup.objects.exists())

    def test_manager_without_create_right_cannot_save_or_start(self):
        manager = self.member()
        self.make_manager_of_alex(manager)
        self.client.force_login(manager)

        for action in ('save', 'start'):
            with self.subTest(action=action):
                response = self.post(action, peer_emails='dana@acme.example')
                self.assertIn(response.status_code, (403, 404))
        self.assertFalse(ReviewSetup.objects.exists())
        self.assertFalse(ReviewCycle.objects.exists())

    def test_manager_without_create_right_sees_no_reviewer_list(self):
        casey = RevieweeFactory(organization=self.org, name='Casey Jones', email='casey@acme.example')
        save_review_setup(
            self.alex, self.questionnaire,
            {'include_self': True, 'include_manager': True, 'include_peer': True, 'include_direct_report': True},
            {'manager': [], 'peer': [casey], 'direct_report': []},
            {'manager': [], 'peer': ['dana@acme.example'], 'direct_report': []})
        manager = self.member()
        self.make_manager_of_alex(manager)
        self.client.force_login(manager)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'dana@acme.example')
        self.assertNotContains(response, 'casey@acme.example')
        self.assertNotContains(response, 'Casey Jones')

    def test_report_reader_without_create_right_cannot_save(self):
        reader = self.member()
        set_user_permission(reader, 'can_view_all_reports', True)
        self.client.force_login(reader)

        response = self.post('save', peer_emails='dana@acme.example')

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ReviewSetup.objects.exists())

    def test_invalid_questionnaire_saves_nothing(self):
        other = QuestionnaireFactory(organization=OrganizationFactory())
        archived = QuestionnaireFactory(organization=self.org, is_active=False)

        for questionnaire in (other, archived):
            for action in ('save', 'start'):
                with self.subTest(questionnaire=questionnaire.name, action=action):
                    self.post(action, questionnaire=questionnaire.id, peer_emails='dana@acme.example')
        self.assertFalse(ReviewSetup.objects.exists())
        self.assertFalse(ReviewCycle.objects.exists())

    def test_create_goes_to_the_list_for_a_user_who_cannot_open_the_page(self):
        inviter = self.member()
        set_user_permission(inviter, 'can_invite_members', True)
        self.client.force_login(inviter)

        response = self.client.post(reverse('reviewee_create'), {'name': 'Dana Visser', 'email': 'dana@acme.example'})

        self.assertTrue(Reviewee.objects.filter(email='dana@acme.example').exists())
        self.assertRedirects(response, reverse('reviewee_list'), fetch_redirect_response=False)

    def test_reviewee_can_save_their_own_list_by_email(self):
        self.client.force_login(self.member(email='alex@acme.example'))

        response = self.post('save', manager_emails='blair@acme.example', peer_emails='dana@acme.example')

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(self.rows(), sorted([('manager', self.blair.pk, ''), ('peer', None, 'dana@acme.example')], key=str))

    def test_create_and_edit_redirect_to_the_page(self):
        response = self.client.post(reverse('reviewee_create'), {'name': 'Dana Visser', 'email': 'dana@acme.example'})
        dana = Reviewee.objects.get(email='dana@acme.example')
        self.assertRedirects(response, reverse('reviewee_detail', args=[dana.uuid]), fetch_redirect_response=False)

        response = self.client.post(reverse('reviewee_edit', args=[self.alex.uuid]), {
            'name': 'Alex Morgan', 'email': 'alex@acme.example', 'department': 'Product Engineering'})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
