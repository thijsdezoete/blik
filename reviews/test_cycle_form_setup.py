from django.test import TestCase
from django.urls import reverse

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory, UserProfileFactory
from accounts.models import ReviewSetup
from accounts.permissions import assign_organization_admin, assign_organization_member
from questionnaires.factories import QuestionnaireFactory
from subscriptions.testing import grant
from reviews.models import ReviewCycle
from reviews.setup import save_review_setup

NO_PEOPLE = {'manager': [], 'peer': [], 'direct_report': []}
NO_EMAILS = {'manager': [], 'peer': [], 'direct_report': []}
ALL_FLAGS = {'include_self': True, 'include_manager': True, 'include_peer': True, 'include_direct_report': True}


class CycleFormSaveTests(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.user = self.profile.user
        self.org = self.profile.organization
        assign_organization_admin(self.user)
        self.client.force_login(self.user)
        self.questionnaire = QuestionnaireFactory(organization=self.org, is_default=True)
        self.alex = RevieweeFactory(organization=self.org, name='Alex Morgan', email='alex@acme.example')
        self.blair = RevieweeFactory(organization=self.org, name='Blair Chen', email='blair@acme.example')

    def post_form(self, **fields):
        return self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'single', 'questionnaire': self.questionnaire.id, 'reviewee': self.alex.id,
            'categories_submitted': '1', 'include_self': 'on', 'include_manager': 'on', 'include_peer': 'on',
            **fields,
        })

    def save_list(self, people=None, emails=None, flags=None):
        save_review_setup(
            self.alex, self.questionnaire, flags or ALL_FLAGS,
            {**NO_PEOPLE, **(people or {})}, {**NO_EMAILS, **(emails or {})})

    def test_sending_the_form_with_reviewers_saves_them_for_the_reviewee(self):
        self.post_form(manager_reviewees=[str(self.blair.uuid)], peer_emails='dana@acme.example')

        saved = ReviewSetup.objects.get(reviewee=self.alex)
        self.assertEqual(saved.questionnaire, self.questionnaire)
        self.assertEqual(
            (saved.include_self, saved.include_manager, saved.include_peer, saved.include_direct_report),
            (True, True, True, False))
        self.assertEqual(
            sorted(saved.reviewers.values_list('category', 'person', 'email'), key=str),
            sorted([('manager', self.blair.pk, ''), ('peer', None, 'dana@acme.example')], key=str))

    def test_a_switched_off_category_keeps_its_people_in_the_list_and_gets_no_tokens(self):
        casey = RevieweeFactory(organization=self.org, name='Casey Jones', email='casey@acme.example')
        self.save_list(people={'manager': [self.blair], 'peer': [casey]}, emails={'peer': ['dana@acme.example']})

        # Peers off; the browser still posts the peer fields it was filled with.
        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'single', 'questionnaire': self.questionnaire.id, 'reviewee': self.alex.id,
            'categories_submitted': '1', 'include_self': 'on', 'include_manager': 'on',
            'manager_reviewees': [str(self.blair.uuid)], 'peer_reviewees': [str(casey.uuid)],
            'peer_emails': 'dana@acme.example'})

        saved = ReviewSetup.objects.get(reviewee=self.alex)
        self.assertFalse(saved.include_peer)
        self.assertEqual(
            sorted(saved.reviewers.values_list('category', 'person', 'email'), key=str),
            sorted([('manager', self.blair.pk, ''), ('peer', casey.pk, ''), ('peer', None, 'dana@acme.example')],
                   key=str))
        cycle = ReviewCycle.objects.get(reviewee=self.alex)
        self.assertEqual(sorted(cycle.tokens.values_list('category', 'reviewer_email')),
                         [('manager', 'blair@acme.example'), ('self', 'alex@acme.example')])

    def test_sending_the_form_without_reviewers_saves_nothing(self):
        self.post_form()

        self.assertFalse(ReviewSetup.objects.exists())


    def test_a_failed_cycle_creation_saves_no_list(self):
        grant(self.org, 0)

        self.post_form(manager_reviewees=[str(self.blair.uuid)], peer_emails='dana@acme.example')

        self.assertFalse(ReviewSetup.objects.exists())
        self.assertFalse(ReviewCycle.objects.exists())

    def test_an_anonymous_request_to_the_form_goes_to_the_login_page(self):
        self.client.logout()

        response = self.client.post(reverse('review_cycle_create'), {'creation_mode': 'single'})

        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])


class FillEndpointTests(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.user = self.profile.user
        self.org = self.profile.organization
        assign_organization_admin(self.user)
        self.client.force_login(self.user)
        self.questionnaire = QuestionnaireFactory(organization=self.org, is_default=True)
        self.alex = RevieweeFactory(organization=self.org, name='Alex Morgan', email='alex@acme.example')
        self.blair = RevieweeFactory(organization=self.org, name='Blair Chen', email='blair@acme.example')

    def fill(self, **params):
        return self.client.get(
            reverse('derive_reviewers_for_cycle'), {'reviewee': self.alex.uuid, **params}).json()

    def save_list(self, people=None, emails=None, flags=None):
        save_review_setup(
            self.alex, self.questionnaire, flags or ALL_FLAGS,
            {**NO_PEOPLE, **(people or {})}, {**NO_EMAILS, **(emails or {})})

    def test_the_fill_endpoint_gives_the_saved_list_before_the_org_chart(self):
        self.save_list(
            people={'manager': [self.blair]}, emails={'peer': ['dana@acme.example']},
            flags={**ALL_FLAGS, 'include_peer': False})

        data = self.fill()

        self.assertEqual(data['source'], 'saved')
        self.assertEqual([p['email'] for p in data['manager']], ['blair@acme.example'])
        self.assertEqual(data['emails'], {**NO_EMAILS, 'peer': ['dana@acme.example']})
        self.assertEqual([p['email'] for p in data['self']], ['alex@acme.example'])
        self.assertFalse(data['flags']['include_peer'])
        self.assertEqual(data['questionnaire'], self.questionnaire.id)

    def test_the_fill_endpoint_with_source_chart_gives_the_org_chart(self):
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.blair, row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.alex, row=1, col=0)
        self.save_list(emails={'peer': ['dana@acme.example']})

        data = self.fill(source='chart')

        self.assertEqual(data['source'], 'chart')
        self.assertEqual([p['email'] for p in data['manager']], ['blair@acme.example'])
        self.assertEqual(data['emails'], NO_EMAILS)

    def test_the_fill_endpoint_gives_only_the_org_chart_to_a_user_who_cannot_create_for_the_person(self):
        self.save_list(people={'manager': [self.blair]}, emails={'peer': ['dana@acme.example']})
        member = UserProfileFactory(organization=self.org).user
        assign_organization_member(member)
        self.client.force_login(member)

        data = self.fill()

        self.assertEqual(data['source'], 'chart')
        self.assertEqual(data['manager'], [])
        self.assertEqual(data['emails'], NO_EMAILS)
        self.assertIsNone(data['questionnaire'])
        self.assertTrue(all(data['flags'].values()))
