from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Reviewee
from core.factories import OrganizationFactory, UserFactory
from accounts.factories import UserProfileFactory, RevieweeFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle


# core.email bypasses Django's test email backend (it builds a live SMTP
# EmailBackend directly), so mail.outbox stays empty even in tests. Instead we
# assert on calls to send_reviewee_notifications — the single integration
# seam between the bulk flow and the email machinery. The view imports this
# function inline (`from reviews.services import ...`), so we patch at the
# source module.
NOTIFY_PATH = 'reviews.services.send_reviewee_notifications'


class BulkCycleCreationTestCase(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.user = UserFactory(username='bulkadmin')
        self.user.set_password('pw')
        self.user.save()
        UserProfileFactory(
            user=self.user,
            organization=self.org,
            can_create_cycles_for_others=True,
        )
        self.questionnaire = QuestionnaireFactory(organization=self.org, is_default=True)
        self.reviewees = [
            RevieweeFactory(organization=self.org, name=f'Reviewee {i}')
            for i in range(3)
        ]
        # Saving a UserProfile auto-creates a Reviewee via post_save signal
        # (accounts/signals.py). Bulk cycle creation targets *every* active
        # reviewee in the org, so derive the expected count at runtime rather
        # than hard-coding len(self.reviewees).
        self.expected_cycle_count = Reviewee.objects.for_organization(
            self.org
        ).filter(is_active=True).count()

        self.client = Client()
        self.client.force_login(self.user)

    def test_bulk_create_does_not_send_emails(self):
        with patch(NOTIFY_PATH) as notify:
            response = self.client.post(
                reverse('review_cycle_create'),
                {
                    'creation_mode': 'bulk',
                    'questionnaire': str(self.questionnaire.id),
                },
            )

        self.assertRedirects(response, reverse('bulk_send_invitations'))
        self.assertEqual(
            ReviewCycle.objects.filter(questionnaire=self.questionnaire).count(),
            self.expected_cycle_count,
        )
        # Critical: bulk create must not trigger the send path.
        notify.assert_not_called()

        # Session carries the new cycle uuids for the confirmation step.
        pending = self.client.session.get('pending_invitation_cycles', [])
        self.assertEqual(len(pending), self.expected_cycle_count)

    def test_bulk_send_invitations_get_lists_pending_cycles(self):
        with patch(NOTIFY_PATH):
            self.client.post(
                reverse('review_cycle_create'),
                {'creation_mode': 'bulk', 'questionnaire': str(self.questionnaire.id)},
            )
        response = self.client.get(reverse('bulk_send_invitations'))
        self.assertEqual(response.status_code, 200)
        for reviewee in self.reviewees:
            self.assertContains(response, reviewee.name)

    def test_bulk_send_invitations_post_fires_notifications(self):
        with patch(NOTIFY_PATH):
            self.client.post(
                reverse('review_cycle_create'),
                {'creation_mode': 'bulk', 'questionnaire': str(self.questionnaire.id)},
            )

        with patch(NOTIFY_PATH) as notify:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse('bulk_send_invitations'))

        self.assertRedirects(response, reverse('review_cycle_list'))
        self.assertEqual(
            notify.call_count, self.expected_cycle_count,
            'One notification call per cycle should be scheduled via on_commit',
        )

        # Session cleared after sends are scheduled.
        self.assertNotIn('pending_invitation_cycles', self.client.session)
