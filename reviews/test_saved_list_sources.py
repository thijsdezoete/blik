from django.test import Client, TestCase
from django.urls import reverse

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory, UserProfileFactory
from accounts.models import ReviewSetup
from accounts.permissions import assign_organization_admin
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.models import ReviewCycle
from reviews.setup import save_review_setup

ALL_FLAGS = {'include_self': True, 'include_manager': True, 'include_peer': True, 'include_direct_report': True}


class SavedListSourcesTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory(username='sourceadmin')
        UserProfileFactory(user=self.admin, organization=self.org, can_create_cycles_for_others=True)
        assign_organization_admin(self.admin)
        self.client = Client()
        self.client.force_login(self.admin)
        self.questionnaire = QuestionnaireFactory(organization=self.org, is_default=True)
        self.alex = RevieweeFactory(organization=self.org, name='Alex Morgan', email='alex@acme.example')
        # Only Alex is in the runs of these tests.
        for person in self.org.reviewees.exclude(pk=self.alex.pk):
            person.is_active = False
            person.save()
        self.blair = RevieweeFactory(organization=self.org, name='Blair Chen', email='blair@acme.example')
        self.dana = RevieweeFactory(organization=self.org, name='Dana Ruiz', email='dana@acme.example')

    def save_list(self, person, peers=(), managers=()):
        return save_review_setup(
            person, self.questionnaire, ALL_FLAGS,
            {'manager': [], 'peer': [], 'direct_report': []},
            {'manager': list(managers), 'peer': list(peers), 'direct_report': []})

    def previous_cycle(self, person, peer='dana@acme.example'):
        cycle = ReviewCycleFactory(reviewee=person, questionnaire=self.questionnaire)
        ReviewerTokenFactory(cycle=cycle, category='peer', reviewer_email=peer)
        return cycle

    def emails(self, cycle, category):
        return set(cycle.tokens.filter(category=category, reviewer_email__isnull=False)
                   .values_list('reviewer_email', flat=True))

    def start_from_list(self, person):
        return self.client.post(reverse('quick_cycle_create', args=[person.uuid]), {
            'questionnaire_id': str(self.questionnaire.id), 'categories_submitted': '1',
            'include_manager': 'on', 'include_peer': 'on'})

    def bulk(self, source, **flags):
        flags = flags or {'include_self': 'on', 'include_manager': 'on', 'include_peer': 'on',
                          'include_direct_report': 'on'}
        return self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk', 'bulk_source': source, 'questionnaire': str(self.questionnaire.id),
            'categories_submitted': '1', **flags})

    def newest_cycle(self, person):
        return ReviewCycle.objects.filter(reviewee=person).order_by('-created_at', '-pk').first()

    def test_list_dialog_uses_the_saved_list(self):
        self.previous_cycle(self.alex, peer='dana@acme.example')
        self.save_list(self.alex, peers=['casey@acme.example'], managers=['blair@acme.example'])
        self.start_from_list(self.alex)
        cycle = self.newest_cycle(self.alex)
        self.assertEqual(self.emails(cycle, 'peer'), {'casey@acme.example'})
        self.assertEqual(self.emails(cycle, 'manager'), {'blair@acme.example'})
        self.assertTrue(cycle.tokens.filter(invitation_queued_at__isnull=False).exists())

    def test_list_dialog_without_a_saved_list_copies_the_previous_cycle(self):
        self.previous_cycle(self.alex, peer='dana@acme.example')
        self.start_from_list(self.alex)
        self.assertEqual(self.emails(self.newest_cycle(self.alex), 'peer'), {'dana@acme.example'})

    def test_bulk_from_chart_uses_the_saved_list_of_a_person(self):
        self.save_list(self.alex, peers=['casey@acme.example'])
        self.bulk('chart')
        self.assertEqual(self.emails(self.newest_cycle(self.alex), 'peer'), {'casey@acme.example'})

    def put_in_chart_under_blair(self, *people):
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.blair, row=0, col=0)
        for col, person in enumerate(people):
            OrgUnitMembershipFactory(unit=unit, reviewee=person, row=1, col=col)

    def test_bulk_from_chart_keeps_the_chart_for_a_person_without_a_list(self):
        self.put_in_chart_under_blair(self.alex, self.dana)
        self.save_list(self.alex, peers=['casey@acme.example'])
        self.bulk('chart')
        self.assertEqual(self.emails(self.newest_cycle(self.dana), 'manager'), {'blair@acme.example'})
        self.assertEqual(self.emails(self.newest_cycle(self.alex), 'peer'), {'casey@acme.example'})
        self.assertEqual(self.emails(self.newest_cycle(self.alex), 'manager'), set())

    def test_bulk_run_limits_the_saved_list_to_its_categories(self):
        self.save_list(self.alex, peers=['casey@acme.example'], managers=['blair@acme.example'])
        self.bulk('chart', include_self='on', include_manager='on')
        cycle = self.newest_cycle(self.alex)
        self.assertEqual(self.emails(cycle, 'manager'), {'blair@acme.example'})
        self.assertEqual(self.emails(cycle, 'peer'), set())

    def test_bulk_empty_ignores_the_saved_list(self):
        self.save_list(self.alex, peers=['casey@acme.example'])
        self.bulk('empty')
        self.assertEqual(self.emails(self.newest_cycle(self.alex), 'peer'), set())

    def test_bulk_run_saves_no_list(self):
        self.put_in_chart_under_blair(self.alex, self.dana)
        self.save_list(self.alex, peers=['casey@acme.example'])
        rows_before = set(self.alex.review_setup.reviewers.values_list('pk', 'category', 'email'))
        self.bulk('chart')
        self.assertTrue(self.emails(self.newest_cycle(self.dana), 'manager'))
        self.assertFalse(ReviewSetup.objects.filter(reviewee=self.dana).exists())
        self.assertEqual(set(self.alex.review_setup.reviewers.values_list('pk', 'category', 'email')), rows_before)

    def test_bulk_from_previous_takes_reviewers_from_the_list_and_the_rest_from_the_previous_cycle(self):
        annual = QuestionnaireFactory(organization=self.org, name='Annual review')
        previous = ReviewCycleFactory(reviewee=self.alex, questionnaire=annual, include_direct_report=False)
        ReviewerTokenFactory(cycle=previous, category='peer', reviewer_email='dana@acme.example')
        self.save_list(self.alex, peers=['casey@acme.example'])
        self.bulk('previous')
        cycle = self.newest_cycle(self.alex)
        self.assertNotEqual(cycle.pk, previous.pk)
        self.assertEqual(cycle.questionnaire, annual)
        self.assertFalse(cycle.include_direct_report)
        self.assertEqual(self.emails(cycle, 'peer'), {'casey@acme.example'})

    def test_bulk_from_previous_skips_a_person_with_a_list_and_no_previous_cycle(self):
        self.save_list(self.alex, peers=['casey@acme.example'])
        self.bulk('previous')
        self.assertIsNone(self.newest_cycle(self.alex))

    def test_bulk_run_makes_no_cycle_for_an_empty_saved_list(self):
        self.put_in_chart_under_blair(self.alex)
        self.save_list(self.alex)
        self.bulk('chart')
        self.assertIsNone(self.newest_cycle(self.alex))

    def test_list_dialog_makes_one_self_token(self):
        self.save_list(self.alex, peers=['casey@acme.example'])
        self.client.post(reverse('quick_cycle_create', args=[self.alex.uuid]), {
            'questionnaire_id': str(self.questionnaire.id), 'categories_submitted': '1',
            'include_self': 'on', 'include_peer': 'on'})
        self.assertEqual(self.newest_cycle(self.alex).tokens.filter(category='self').count(), 1)
