from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.factories import RevieweeFactory, UserProfileFactory
from accounts.import_service import import_reports, import_review_cycles
from accounts.models import Reviewee
from accounts.permissions import assign_organization_admin
from api.models import APIToken
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle
from subscriptions.testing import grant, subscribe
from subscriptions.utils import NoCycleCredits, cycle_credits

NOTIFY_PATH = 'reviews.services.send_reviewee_notifications'


class CycleGateBase(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.user = UserFactory()
        UserProfileFactory(user=self.user, organization=self.org,
                           can_create_cycles_for_others=True)
        assign_organization_admin(self.user)
        self.questionnaire = QuestionnaireFactory(organization=self.org, is_default=True)
        self.reviewees = [
            RevieweeFactory(organization=self.org, name=f'Reviewee {i}') for i in range(3)
        ]
        self.reviewee = self.reviewees[0]
        # A UserProfile auto-creates a Reviewee for its user (accounts/signals.py).
        self.active_reviewees = Reviewee.objects.for_organization(
            self.org).filter(is_active=True).count()
        self.client = Client()
        self.client.force_login(self.user)

    def cycles(self):
        return ReviewCycle.objects.filter(reviewee__organization=self.org).count()


class ModelGateTests(CycleGateBase):
    def create(self):
        return ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)

    def test_creating_a_cycle_spends_one_credit(self):
        grant(self.org, 2)
        self.create()
        self.assertEqual(cycle_credits(self.org), 1)

    def test_no_credit_no_cycle(self):
        grant(self.org, 0)
        with self.assertRaises(NoCycleCredits):
            self.create()
        self.assertEqual(self.cycles(), 0)

    def test_saving_an_existing_cycle_spends_nothing(self):
        grant(self.org, 2)
        cycle = self.create()
        cycle.status = 'completed'
        cycle.save()
        self.assertEqual(cycle_credits(self.org), 1)

    def test_failed_insert_gives_the_credit_back(self):
        grant(self.org, 2)
        with self.assertRaises(IntegrityError):
            ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=None)
        self.assertEqual(cycle_credits(self.org), 2)

    def test_subscription_and_self_hosted_organizations_are_not_charged(self):
        self.create()                       # self_hosted: allowed
        subscribe(self.org)
        grant(self.org, 0)
        self.create()                       # active subscription: allowed, balance untouched
        self.assertEqual(self.cycles(), 2)

    def test_canceled_subscriber_with_credits_can_create(self):
        subscribe(self.org, status='canceled')
        grant(self.org, 1)
        self.create()
        self.assertEqual(cycle_credits(self.org), 0)


class DashboardEntryPointTests(CycleGateBase):
    def quick(self):
        return self.client.post(
            reverse('quick_cycle_create', args=[self.reviewee.id]),
            {'questionnaire_id': str(self.questionnaire.id)},
        )

    def single(self):
        with patch(NOTIFY_PATH):
            return self.client.post(reverse('review_cycle_create'), {
                'creation_mode': 'single',
                'questionnaire': str(self.questionnaire.id),
                'reviewee': str(self.reviewee.id),
            })

    def bulk(self):
        with patch(NOTIFY_PATH):
            return self.client.post(reverse('review_cycle_create'), {
                'creation_mode': 'bulk',
                'questionnaire': str(self.questionnaire.id),
            })

    def test_quick_create_spends_a_credit(self):
        grant(self.org, 1)
        self.quick()
        self.assertEqual((self.cycles(), cycle_credits(self.org)), (1, 0))

    def test_quick_create_is_refused_at_zero(self):
        grant(self.org, 0)
        response = self.quick()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.cycles(), 0)

    def test_single_create_spends_a_credit(self):
        grant(self.org, 1)
        self.single()
        self.assertEqual((self.cycles(), cycle_credits(self.org)), (1, 0))

    def test_single_create_is_refused_at_zero(self):
        grant(self.org, 0)
        response = self.single()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.cycles(), 0)

    def test_bulk_create_spends_one_credit_per_cycle(self):
        grant(self.org, self.active_reviewees + 2)
        self.bulk()
        self.assertEqual((self.cycles(), cycle_credits(self.org)), (self.active_reviewees, 2))

    def test_bulk_create_short_of_credits_creates_and_spends_nothing(self):
        grant(self.org, self.active_reviewees - 1)
        self.bulk()
        self.assertEqual(self.cycles(), 0)
        self.assertEqual(cycle_credits(self.org), self.active_reviewees - 1)


class ApiEntryPointTests(CycleGateBase):
    def setUp(self):
        super().setUp()
        token = APIToken.objects.create(organization=self.org, created_by=self.user, name='t')
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token.token}')

    def post(self):
        return self.api.post('/api/v1/cycles/', {
            'reviewee': str(self.reviewee.uuid),
            'questionnaire': str(self.questionnaire.uuid),
            'send_invitations': False,
        }, format='json')

    def test_api_create_spends_a_credit(self):
        grant(self.org, 1)
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(cycle_credits(self.org), 0)

    def test_api_create_is_refused_at_zero_with_400(self):
        grant(self.org, 0)
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.cycles(), 0)


class ImportEntryPointTests(CycleGateBase):
    def test_cycle_import_short_of_credits_aborts_and_spends_nothing(self):
        grant(self.org, 1)
        data = [{'reviewee': r.name, 'questionnaire': self.questionnaire.name}
                for r in self.reviewees[:2]]
        with self.assertRaises(NoCycleCredits):
            with transaction.atomic():   # import_organization_data wraps the import like this
                import_review_cycles(self.org, data, {})
        self.assertEqual((self.cycles(), cycle_credits(self.org)), (0, 1))

    def test_cycle_import_with_enough_credits_spends_them(self):
        grant(self.org, 2)
        data = [{'reviewee': r.name, 'questionnaire': self.questionnaire.name}
                for r in self.reviewees[:2]]
        import_review_cycles(self.org, data, {})
        self.assertEqual((self.cycles(), cycle_credits(self.org)), (2, 0))

    def test_report_import_without_credits_aborts(self):
        grant(self.org, 0)
        data = [{'reviewee': self.reviewee.name, 'questionnaire_name': self.questionnaire.name}]
        with self.assertRaises(NoCycleCredits):
            with transaction.atomic():
                import_reports(self.org, data, {})
        self.assertEqual(self.cycles(), 0)
