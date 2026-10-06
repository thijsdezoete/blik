"""Tests for the email-dispatch services in reviews.services.

We patch `reviews.services.send_email` rather than relying on Django's
locmem backend because `core.email.send_email` builds an SMTP backend from
the Organization row and bypasses the test mail outbox.
"""
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from accounts.factories import RevieweeFactory
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.services import (
    send_reviewee_notifications,
    send_reviewer_invitations,
)


class SendReviewerInvitationsTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.reviewee = RevieweeFactory(
            organization=self.org, email='reviewee@example.com',
        )
        self.cycle = ReviewCycleFactory(
            reviewee=self.reviewee,
            questionnaire=QuestionnaireFactory(organization=self.org),
            created_by=UserFactory(),
        )

    @patch('reviews.services.send_email')
    def test_does_not_send_to_self_category_tokens(self, mock_send_email):
        """Self-category tokens already receive a dedicated self-assessment
        email from send_reviewee_notifications. Sending the generic
        reviewer invitation in addition delivers two emails to the same
        person with different subjects and bodies.
        """
        ReviewerTokenFactory(
            cycle=self.cycle, category='self',
            reviewer_email=self.reviewee.email,
        )
        ReviewerTokenFactory(
            cycle=self.cycle, category='manager',
            reviewer_email='manager@example.com',
        )

        stats = send_reviewer_invitations(self.cycle)

        recipients = {
            address
            for call in mock_send_email.call_args_list
            for address in call.kwargs['recipient_list']
        }
        self.assertEqual(recipients, {'manager@example.com'})
        self.assertEqual(stats['sent'], 1)


@override_settings(SITE_DOMAIN='public.example.com', SITE_PROTOCOL='https')
class SendRevieweeNotificationsTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.reviewee = RevieweeFactory(
            organization=self.org, email='reviewee@example.com',
        )
        self.cycle = ReviewCycleFactory(
            reviewee=self.reviewee,
            questionnaire=QuestionnaireFactory(organization=self.org),
            created_by=UserFactory(),
        )

    @patch('reviews.services.send_email')
    def test_uses_site_domain_not_request_host_for_links(self, mock_send_email):
        """Links must always point at SITE_DOMAIN. A request passed in from
        a view may carry a proxy hostname (HTTP_HOST set to the internal
        upstream) — using it would produce links that recipients can't
        reach.
        """
        request = RequestFactory().get('/', HTTP_HOST='proxy.internal:8000')

        send_reviewee_notifications(self.cycle, request=request)

        rendered = '\n'.join(
            (call.kwargs.get('html_message') or '')
            + '\n'
            + call.kwargs['message']
            for call in mock_send_email.call_args_list
        )
        self.assertIn('https://public.example.com/', rendered)
        self.assertNotIn('proxy.internal', rendered)


class SendSelfAssessmentInviteTests(TestCase):
    """GitHub #20: the per-reviewer "Send Invite" button on a self-assessment
    token said "No pending invitations to send" because the view ignored
    token_id and the service always excluded the self category."""

    def setUp(self):
        self.org = OrganizationFactory()
        self.reviewee = RevieweeFactory(organization=self.org, email='reviewee@example.com')
        self.cycle = ReviewCycleFactory(
            reviewee=self.reviewee,
            questionnaire=QuestionnaireFactory(organization=self.org),
            created_by=UserFactory(),
        )
        self.token = ReviewerTokenFactory(
            cycle=self.cycle, category='self', reviewer_email=self.reviewee.email,
        )

    @patch('reviews.services.send_email')
    def test_explicit_token_id_sends_self_assessment_email(self, mock_send_email):
        stats = send_reviewer_invitations(self.cycle, token_ids=[self.token.id])

        self.assertEqual(stats['sent'], 1)
        kwargs = mock_send_email.call_args.kwargs
        self.assertEqual(kwargs['recipient_list'], ['reviewee@example.com'])
        self.assertIn('Self-Assessment', kwargs['subject'])
        self.assertIn(f'/feedback/{self.token.token}/', kwargs['message'])
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.invitation_sent_at)
