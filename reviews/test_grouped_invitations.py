"""Tests for send_grouped_invitations: one invitation email per address.

`reviews.services.send_email` is patched, as in test_email_services: core.email builds its
own SMTP backend and bypasses the test outbox.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.factories import RevieweeFactory
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.models import ReviewerToken
from reviews.services import feedback_overview_url, send_grouped_invitations


@override_settings(SITE_DOMAIN='public.example.com', SITE_PROTOCOL='https')
class SendGroupedInvitationsTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.cycle_a = ReviewCycleFactory(
            reviewee=RevieweeFactory(organization=self.org, name='Alice'),
            questionnaire=QuestionnaireFactory(organization=self.org),
            created_by=UserFactory(),
        )
        self.cycle_b = ReviewCycleFactory(
            reviewee=RevieweeFactory(organization=self.org, name='Bob'),
            questionnaire=QuestionnaireFactory(organization=self.org),
            created_by=UserFactory(),
        )

    def pending(self):
        return ReviewerToken.objects.filter(reviewer_email__isnull=False, invitation_sent_at__isnull=True)

    @patch('reviews.services.send_email')
    def test_same_address_across_two_cycles_gets_one_email(self, mock_send_email):
        token_a = ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com')
        token_b = ReviewerTokenFactory(cycle=self.cycle_b, category='manager', reviewer_email='carol@example.com')

        stats = send_grouped_invitations(self.pending())

        self.assertEqual(mock_send_email.call_count, 1)
        self.assertEqual(stats, {'sent': 1, 'tokens': 2, 'errors': []})
        kwargs = mock_send_email.call_args.kwargs
        self.assertEqual(kwargs['recipient_list'], ['carol@example.com'])
        for body in (kwargs['message'], kwargs['html_message']):
            self.assertIn(f'https://public.example.com/feedback/{token_a.token}/', body)
            self.assertIn(f'https://public.example.com/feedback/{token_b.token}/', body)
            self.assertIn(feedback_overview_url('carol@example.com', self.org), body)
            self.assertIn('Alice', body)
            self.assertIn('Bob', body)

    @patch('reviews.services.send_email')
    def test_different_addresses_get_one_email_each(self, mock_send_email):
        ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com')
        ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='dave@example.com')

        stats = send_grouped_invitations(self.pending())

        recipients = sorted(
            address
            for call in mock_send_email.call_args_list
            for address in call.kwargs['recipient_list']
        )
        self.assertEqual(recipients, ['carol@example.com', 'dave@example.com'])
        self.assertEqual(stats['sent'], 2)
        self.assertEqual(stats['tokens'], 2)

    @patch('reviews.services.send_email')
    def test_single_token_uses_the_normal_invitation(self, mock_send_email):
        token = ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com')

        send_grouped_invitations(self.pending())

        kwargs = mock_send_email.call_args.kwargs
        self.assertEqual(kwargs['subject'], 'Your feedback for Alice')
        self.assertIn(f'/feedback/{token.token}/', kwargs['message'])
        self.assertNotIn('/feedback/overview/', kwargs['message'])

    @patch('reviews.services.send_email')
    def test_marks_every_token_in_the_group_sent(self, mock_send_email):
        ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com')
        ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='carol@example.com')
        ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='dave@example.com')

        send_grouped_invitations(self.pending())

        self.assertFalse(self.pending().exists())
        self.assertEqual(ReviewerToken.objects.filter(invitation_sent_at__isnull=False).count(), 3)

    @patch('reviews.services.send_email')
    def test_addresses_differing_only_by_case_are_one_group(self, mock_send_email):
        ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='Carol@Example.com')
        ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='carol@example.com')

        stats = send_grouped_invitations(self.pending())

        self.assertEqual(mock_send_email.call_count, 1)
        self.assertEqual(stats['tokens'], 2)
        self.assertEqual(mock_send_email.call_args.kwargs['recipient_list'], ['carol@example.com'])

    @patch('reviews.services.send_email')
    def test_bundle_names_the_self_assessment(self, mock_send_email):
        reviewee = self.cycle_a.reviewee
        reviewee.email = 'alice@example.com'
        reviewee.save()
        ReviewerTokenFactory(cycle=self.cycle_a, category='self', reviewer_email='alice@example.com')
        ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='alice@example.com')

        send_grouped_invitations(self.pending())

        self.assertIn('Your own self-assessment', mock_send_email.call_args.kwargs['message'])
