from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Reviewee
from core.factories import OrganizationFactory, UserFactory
from accounts.factories import UserProfileFactory, RevieweeFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle, ReviewerToken


# The bulk views put the emails in the outbox; the send_queued_invitations cron sends them.
# So the tests assert on the queue, and that the request itself sends nothing:
# `reviews.services.send_email` is the one seam every email goes through.
SEND_MAIL = 'reviews.services.send_email'


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

    def create_bulk(self):
        return self.client.post(
            reverse('review_cycle_create'),
            {'creation_mode': 'bulk', 'questionnaire': str(self.questionnaire.id)},
        )

    def queued_tokens(self):
        return ReviewerToken.objects.filter(invitation_queued_at__isnull=False)

    def test_bulk_create_does_not_send_or_queue_emails(self):
        with patch(SEND_MAIL) as send:
            response = self.create_bulk()

        self.assertRedirects(response, reverse('bulk_send_invitations'))
        self.assertEqual(
            ReviewCycle.objects.filter(questionnaire=self.questionnaire).count(),
            self.expected_cycle_count,
        )
        # Critical: bulk create must not trigger the send path.
        send.assert_not_called()
        self.assertFalse(self.queued_tokens().exists())
        self.assertFalse(ReviewCycle.objects.filter(links_email_queued_at__isnull=False).exists())

        # Session carries the new cycle uuids for the confirmation step.
        pending = self.client.session.get('pending_invitation_cycles', [])
        self.assertEqual(len(pending), self.expected_cycle_count)

    def test_bulk_send_invitations_get_lists_pending_cycles(self):
        self.create_bulk()
        response = self.client.get(reverse('bulk_send_invitations'))
        self.assertEqual(response.status_code, 200)
        for reviewee in self.reviewees:
            self.assertContains(response, reviewee.name)

    def test_bulk_send_invitations_post_queues_the_reviewee_emails(self):
        """Without reviewer addresses, every reviewee gets their self-assessment and the links
        to share. Both wait in the outbox; the request sends nothing."""
        self.create_bulk()

        with patch(SEND_MAIL) as send:
            response = self.client.post(reverse('bulk_send_invitations'))

        self.assertRedirects(response, reverse('review_cycle_list'))
        send.assert_not_called()
        cycles = ReviewCycle.objects.filter(questionnaire=self.questionnaire)
        self.assertEqual(cycles.filter(links_email_queued_at__isnull=False).count(), self.expected_cycle_count)
        self.assertEqual(self.queued_tokens().filter(category='self').count(), self.expected_cycle_count)

        # Session cleared once the emails are queued.
        self.assertNotIn('pending_invitation_cycles', self.client.session)

    def test_chart_bulk_send_queues_every_reviewer_invitation_and_no_reviewee_email(self):
        """Chart-derived cycles carry reviewer emails. Every pending token goes in the outbox,
        where the cron groups them per address; the reviewee gets no separate self-assessment
        or links email, their self-assessment rides along in their bundle."""
        from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory

        cycles = [
            ReviewCycleFactory(reviewee=reviewee, questionnaire=self.questionnaire, created_by=self.user)
            for reviewee in self.reviewees[:2]
        ]
        tokens = [
            ReviewerTokenFactory(cycle=cycle, category='peer', reviewer_email='carol@example.com')
            for cycle in cycles
        ] + [
            ReviewerTokenFactory(cycle=cycle, category='self', reviewer_email=cycle.reviewee.email)
            for cycle in cycles
        ]
        session = self.client.session
        session['pending_invitation_cycles'] = [str(c.uuid) for c in cycles]
        session['pending_bulk_source'] = 'chart'
        session.save()

        with patch(SEND_MAIL) as send:
            response = self.client.post(reverse('bulk_send_invitations'), follow=True)

        send.assert_not_called()
        self.assertEqual(set(self.queued_tokens()), set(tokens))
        self.assertFalse(ReviewCycle.objects.filter(links_email_queued_at__isnull=False).exists())
        # Four invitations, three addresses: carol's two forms go in one email
        self.assertContains(response, '4 reviewer invitations go out in 3 emails')
