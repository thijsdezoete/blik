"""Tests for the email outbox: queueing, and the cron that sends one email per address.

`reviews.services.send_email` is patched, as in test_email_services: core.email builds its
own SMTP backend and bypasses the test outbox when an organization has SMTP settings.
"""
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.factories import RevieweeFactory
from core.factories import OrganizationFactory, UserFactory
from notifications.models import CronRun
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.models import ReviewCycle, ReviewerToken
from reviews.outbox import (
    MAX_ATTEMPTS,
    queue_invitations,
    queue_reminders,
    queue_reviewee_notifications,
    send_queued_emails,
)
from reviews.services import feedback_overview_url

SEND_MAIL = 'reviews.services.send_email'


class OutboxTestCase(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.cycle_a = ReviewCycleFactory(
            reviewee=RevieweeFactory(organization=self.org, name='Alice', email='alice@example.com'),
            questionnaire=QuestionnaireFactory(organization=self.org),
            created_by=UserFactory(),
        )
        self.cycle_b = ReviewCycleFactory(
            reviewee=RevieweeFactory(organization=self.org, name='Bob', email='bob@example.com'),
            questionnaire=QuestionnaireFactory(organization=self.org),
            created_by=UserFactory(),
        )

    def queued_invitations(self):
        return ReviewerToken.objects.filter(invitation_queued_at__isnull=False)

    def queued_reminders(self):
        return ReviewerToken.objects.filter(reminder_queued_at__isnull=False)

    def recipients(self, send):
        return sorted(address for call in send.call_args_list for address in call.kwargs['recipient_list'])


class QueueInvitationsTests(OutboxTestCase):
    def test_queues_the_addressed_unsent_unfinished_tokens_only(self):
        pending = ReviewerTokenFactory(cycle=self.cycle_a, reviewer_email='carol@example.com')
        ReviewerTokenFactory(cycle=self.cycle_a, reviewer_email='dave@example.com', invitation_sent_at=timezone.now())
        ReviewerTokenFactory(cycle=self.cycle_a, reviewer_email='erin@example.com', completed_at=timezone.now())
        ReviewerTokenFactory(cycle=self.cycle_a, reviewer_email=None)
        ReviewerTokenFactory(cycle=self.cycle_a, reviewer_email='')

        queued = queue_invitations(self.cycle_a.tokens.all())

        self.assertEqual(queued, 1)
        self.assertEqual(list(self.queued_invitations()), [pending])

    def test_queueing_again_gives_a_failed_token_a_fresh_start(self):
        token = ReviewerTokenFactory(
            cycle=self.cycle_a, reviewer_email='carol@example.com',
            invitation_queued_at=timezone.now(), email_error='SMTPAuthenticationError', email_attempts=MAX_ATTEMPTS,
        )

        queue_invitations(ReviewerToken.objects.filter(pk=token.pk))

        token.refresh_from_db()
        self.assertEqual((token.email_error, token.email_attempts), ('', 0))


class QueueRemindersTests(OutboxTestCase):
    def test_queues_the_invited_unfinished_tokens_only(self):
        invited = ReviewerTokenFactory(cycle=self.cycle_a, reviewer_email='carol@example.com', invitation_sent_at=timezone.now())
        ReviewerTokenFactory(cycle=self.cycle_a, reviewer_email='dave@example.com')
        ReviewerTokenFactory(
            cycle=self.cycle_a, reviewer_email='erin@example.com',
            invitation_sent_at=timezone.now(), completed_at=timezone.now(),
        )

        queued = queue_reminders(self.cycle_a.tokens.all())

        self.assertEqual(queued, 1)
        self.assertEqual(list(self.queued_reminders()), [invited])


class QueueRevieweeNotificationsTests(OutboxTestCase):
    def test_queues_the_self_assessment_and_the_links_email(self):
        queued = queue_reviewee_notifications(self.cycle_a)

        self.cycle_a.refresh_from_db()
        [self_token] = self.cycle_a.tokens.filter(category='self')
        self.assertEqual(queued, 2)
        self.assertEqual(self_token.reviewer_email, 'alice@example.com')
        self.assertIsNotNone(self_token.invitation_queued_at)
        self.assertIsNotNone(self.cycle_a.links_email_queued_at)

    def test_a_self_only_cycle_gets_no_links_email(self):
        cycle = ReviewCycleFactory(
            reviewee=self.cycle_a.reviewee, questionnaire=self.cycle_a.questionnaire,
            include_peer=False, include_manager=False, include_direct_report=False,
        )

        queued = queue_reviewee_notifications(cycle)

        cycle.refresh_from_db()
        self.assertEqual(queued, 1)
        self.assertIsNone(cycle.links_email_queued_at)

    def test_a_cycle_without_self_assessment_gets_only_the_links_email(self):
        cycle = ReviewCycleFactory(
            reviewee=self.cycle_a.reviewee, questionnaire=self.cycle_a.questionnaire, include_self=False,
        )

        queued = queue_reviewee_notifications(cycle)

        self.assertEqual(queued, 1)
        self.assertFalse(cycle.tokens.filter(category='self').exists())

    def test_a_sent_self_assessment_is_not_queued_again(self):
        ReviewerTokenFactory(
            cycle=self.cycle_a, category='self', reviewer_email='alice@example.com', invitation_sent_at=timezone.now(),
        )

        queue_reviewee_notifications(self.cycle_a)

        self.assertFalse(self.queued_invitations().exists())

    def test_a_reviewee_without_an_address_gets_nothing(self):
        self.cycle_a.reviewee.email = ''
        self.cycle_a.reviewee.save()

        queued = queue_reviewee_notifications(self.cycle_a)

        self.cycle_a.refresh_from_db()
        self.assertEqual(queued, 0)
        self.assertIsNone(self.cycle_a.links_email_queued_at)
        self.assertFalse(self.cycle_a.tokens.exists())


@override_settings(SITE_DOMAIN='public.example.com', SITE_PROTOCOL='https')
class SendQueuedInvitationsTests(OutboxTestCase):
    def queue(self, *tokens):
        queue_invitations(ReviewerToken.objects.filter(pk__in=[t.pk for t in tokens]))

    @patch(SEND_MAIL)
    def test_same_address_across_two_cycles_gets_one_email(self, send):
        token_a = ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com')
        token_b = ReviewerTokenFactory(cycle=self.cycle_b, category='manager', reviewer_email='carol@example.com')
        self.queue(token_a, token_b)

        stats = send_queued_emails()

        self.assertEqual(send.call_count, 1)
        self.assertEqual(stats, {'sent': 1, 'tokens': 2, 'errors': []})
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['recipient_list'], ['carol@example.com'])
        self.assertEqual(kwargs['subject'], f'Your feedback forms for {self.org.name}')
        for body in (kwargs['message'], kwargs['html_message']):
            self.assertIn(f'https://public.example.com/feedback/{token_a.token}/', body)
            self.assertIn(f'https://public.example.com/feedback/{token_b.token}/', body)
            self.assertIn(feedback_overview_url('carol@example.com', self.org), body)
            self.assertIn('Alice', body)
            self.assertIn('Bob', body)

    @patch(SEND_MAIL)
    def test_different_addresses_get_one_email_each(self, send):
        self.queue(
            ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com'),
            ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='dave@example.com'),
        )

        stats = send_queued_emails()

        self.assertEqual(self.recipients(send), ['carol@example.com', 'dave@example.com'])
        self.assertEqual((stats['sent'], stats['tokens']), (2, 2))

    @patch(SEND_MAIL)
    def test_the_same_address_in_two_organizations_gets_one_email_per_organization(self, send):
        other_org = OrganizationFactory()
        other_cycle = ReviewCycleFactory(
            reviewee=RevieweeFactory(organization=other_org, name='Oscar'),
            questionnaire=QuestionnaireFactory(organization=other_org),
        )
        self.queue(
            ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com'),
            ReviewerTokenFactory(cycle=other_cycle, category='peer', reviewer_email='carol@example.com'),
        )

        send_queued_emails()

        self.assertEqual(self.recipients(send), ['carol@example.com', 'carol@example.com'])
        subjects = sorted(call.kwargs['subject'] for call in send.call_args_list)
        self.assertEqual(subjects, ['Your feedback for Alice', 'Your feedback for Oscar'])

    @patch(SEND_MAIL)
    def test_single_token_uses_the_normal_invitation(self, send):
        token = ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com')
        self.queue(token)

        send_queued_emails()

        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['subject'], 'Your feedback for Alice')
        self.assertIn(f'/feedback/{token.token}/', kwargs['message'])
        self.assertNotIn('/feedback/overview/', kwargs['message'])

    @patch(SEND_MAIL)
    def test_a_single_self_assessment_uses_the_self_assessment_email(self, send):
        self.queue(ReviewerTokenFactory(cycle=self.cycle_a, category='self', reviewer_email='alice@example.com'))

        send_queued_emails()

        self.assertIn('self-assessment', send.call_args.kwargs['subject'])

    @patch(SEND_MAIL)
    def test_marks_every_token_in_the_group_sent_and_leaves_the_queue(self, send):
        self.queue(
            ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com'),
            ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='carol@example.com'),
            ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='dave@example.com'),
        )

        send_queued_emails()

        self.assertFalse(self.queued_invitations().exists())
        self.assertEqual(ReviewerToken.objects.filter(invitation_sent_at__isnull=False).count(), 3)

    @patch(SEND_MAIL)
    def test_a_second_run_sends_nothing(self, send):
        self.queue(ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com'))
        send_queued_emails()
        send.reset_mock()

        stats = send_queued_emails()

        send.assert_not_called()
        self.assertEqual(stats, {'sent': 0, 'tokens': 0, 'errors': []})

    @patch(SEND_MAIL)
    def test_addresses_differing_only_by_case_are_one_group(self, send):
        self.queue(
            ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='Carol@Example.com'),
            ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='carol@example.com'),
        )

        stats = send_queued_emails()

        self.assertEqual(send.call_count, 1)
        self.assertEqual(stats['tokens'], 2)
        self.assertEqual(send.call_args.kwargs['recipient_list'], ['carol@example.com'])

    @patch(SEND_MAIL)
    def test_bundle_names_the_self_assessment(self, send):
        self.queue(
            ReviewerTokenFactory(cycle=self.cycle_a, category='self', reviewer_email='alice@example.com'),
            ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='alice@example.com'),
        )

        send_queued_emails()

        self.assertIn('Your own self-assessment', send.call_args.kwargs['message'])

    @patch(SEND_MAIL)
    def test_every_email_of_a_run_goes_through_one_connection(self, send):
        self.queue(
            ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com'),
            ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='dave@example.com'),
        )

        send_queued_emails()

        connections = {id(call.kwargs['connection']) for call in send.call_args_list}
        self.assertEqual(len(connections), 1)
        self.assertIsNotNone(send.call_args.kwargs['connection'])

    @patch(SEND_MAIL)
    def test_a_finished_review_or_a_closed_cycle_leaves_the_queue_unsent(self, send):
        finished = ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com')
        closed = ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='dave@example.com')
        self.queue(finished, closed)
        ReviewerToken.objects.filter(pk=finished.pk).update(completed_at=timezone.now())
        ReviewCycle.objects.filter(pk=self.cycle_b.pk).update(status='completed')

        send_queued_emails()

        send.assert_not_called()
        self.assertFalse(self.queued_invitations().exists())
        self.assertFalse(ReviewerToken.objects.filter(invitation_sent_at__isnull=False).exists())


@override_settings(SITE_DOMAIN='public.example.com', SITE_PROTOCOL='https')
class FailedSendTests(OutboxTestCase):
    def setUp(self):
        super().setUp()
        self.token = ReviewerTokenFactory(cycle=self.cycle_a, category='peer', reviewer_email='carol@example.com')
        self.other = ReviewerTokenFactory(cycle=self.cycle_b, category='peer', reviewer_email='dave@example.com')
        queue_invitations(ReviewerToken.objects.all())

    def failing_for_carol(self, **kwargs):
        if kwargs['recipient_list'] == ['carol@example.com']:
            raise ConnectionRefusedError('Connection refused')
        return 1

    @patch(SEND_MAIL)
    def test_a_failure_is_recorded_on_the_tokens_and_stops_nobody_else(self, send):
        send.side_effect = self.failing_for_carol

        with self.assertLogs('reviews.outbox', level='ERROR'):
            stats = send_queued_emails()

        self.token.refresh_from_db()
        self.other.refresh_from_db()
        self.assertIsNone(self.token.invitation_sent_at)
        self.assertIsNotNone(self.token.invitation_queued_at)
        self.assertEqual(self.token.email_error, 'ConnectionRefusedError: Connection refused')
        self.assertEqual(self.token.email_attempts, 1)
        self.assertIsNotNone(self.other.invitation_sent_at)
        self.assertEqual(stats['sent'], 1)
        self.assertEqual(stats['errors'], ['Failed to send to carol@example.com: ConnectionRefusedError: Connection refused'])

    @patch(SEND_MAIL)
    def test_a_failed_email_is_tried_again_on_the_next_run(self, send):
        send.side_effect = self.failing_for_carol
        with self.assertLogs('reviews.outbox', level='ERROR'):
            send_queued_emails()
        send.side_effect = None

        send_queued_emails()

        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.invitation_sent_at)
        self.assertIsNone(self.token.invitation_queued_at)
        self.assertEqual((self.token.email_error, self.token.email_attempts), ('', 0))

    @patch(SEND_MAIL)
    def test_after_the_last_attempt_the_email_stays_failed_in_the_queue(self, send):
        send.side_effect = self.failing_for_carol
        with self.assertLogs('reviews.outbox', level='ERROR'):
            for _ in range(MAX_ATTEMPTS):
                send_queued_emails()
        send.reset_mock()

        send_queued_emails()

        self.token.refresh_from_db()
        self.assertEqual(self.token.email_attempts, MAX_ATTEMPTS)
        self.assertIsNotNone(self.token.invitation_queued_at)
        self.assertEqual(self.recipients(send), [])

    @patch(SEND_MAIL)
    def test_a_mail_server_that_refuses_the_connection_fails_every_queued_email_at_once(self, send):
        connection = patch('reviews.outbox.get_email_backend').start()
        self.addCleanup(patch.stopall)
        connection.return_value.open.side_effect = OSError('Connection refused')

        with self.assertLogs('reviews.outbox', level='ERROR'):
            stats = send_queued_emails()

        send.assert_not_called()
        self.token.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.token.email_error, 'OSError: Connection refused')
        self.assertEqual(self.other.email_attempts, 1)
        self.assertEqual(stats['errors'], ['Could not connect to the mail server: OSError: Connection refused'])


@override_settings(SITE_DOMAIN='public.example.com', SITE_PROTOCOL='https')
class SendQueuedRemindersTests(OutboxTestCase):
    def invited(self, cycle, email, category='peer'):
        return ReviewerTokenFactory(cycle=cycle, category=category, reviewer_email=email, invitation_sent_at=timezone.now())

    @patch(SEND_MAIL)
    def test_one_open_form_gets_the_normal_reminder(self, send):
        token = self.invited(self.cycle_a, 'carol@example.com')
        queue_reminders(ReviewerToken.objects.all())

        send_queued_emails()

        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['subject'], 'Your feedback for Alice is still open')
        self.assertIn(f'/feedback/{token.token}/', kwargs['message'])
        token.refresh_from_db()
        self.assertIsNotNone(token.last_reminder_sent_at)
        self.assertIsNone(token.reminder_queued_at)

    @patch(SEND_MAIL)
    def test_several_open_forms_get_one_reminder_with_every_link(self, send):
        token_a = self.invited(self.cycle_a, 'carol@example.com')
        token_b = self.invited(self.cycle_b, 'carol@example.com', category='manager')
        queue_reminders(ReviewerToken.objects.all())

        stats = send_queued_emails()

        self.assertEqual(send.call_count, 1)
        self.assertEqual(stats, {'sent': 1, 'tokens': 2, 'errors': []})
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['subject'], f'Your feedback forms for {self.org.name} are still open')
        for body in (kwargs['message'], kwargs['html_message']):
            self.assertIn('You still have 2 forms to fill in', body)
            self.assertIn(f'/feedback/{token_a.token}/', body)
            self.assertIn(f'/feedback/{token_b.token}/', body)
        self.assertIn('Open the review', kwargs['html_message'])
        self.assertEqual(ReviewerToken.objects.filter(last_reminder_sent_at__isnull=False).count(), 2)
        self.assertFalse(self.queued_reminders().exists())

    @patch(SEND_MAIL)
    def test_the_reminder_leaves_out_forms_finished_in_the_meantime(self, send):
        open_token = self.invited(self.cycle_a, 'carol@example.com')
        finished = self.invited(self.cycle_b, 'carol@example.com')
        queue_reminders(ReviewerToken.objects.all())
        ReviewerToken.objects.filter(pk=finished.pk).update(completed_at=timezone.now())

        send_queued_emails()

        kwargs = send.call_args.kwargs
        self.assertIn(f'/feedback/{open_token.token}/', kwargs['message'])
        self.assertNotIn(f'/feedback/{finished.token}/', kwargs['message'])

    @patch(SEND_MAIL)
    def test_a_self_assessment_reminder_speaks_to_the_reviewee(self, send):
        self.invited(self.cycle_a, 'alice@example.com', category='self')
        queue_reminders(ReviewerToken.objects.all())

        send_queued_emails()

        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['recipient_list'], ['alice@example.com'])
        self.assertIn('Your self-assessment is still open', kwargs['subject'])


@override_settings(SITE_DOMAIN='public.example.com', SITE_PROTOCOL='https')
class SendQueuedLinksEmailTests(OutboxTestCase):
    @patch(SEND_MAIL)
    def test_the_reviewee_gets_the_links_to_share(self, send):
        queue_reviewee_notifications(self.cycle_a)

        stats = send_queued_emails()

        self.assertEqual(stats['sent'], 2)
        [links] = [call.kwargs for call in send.call_args_list if 'links to share' in call.kwargs['subject']]
        self.assertEqual(links['recipient_list'], ['alice@example.com'])
        self.assertIn(f'https://public.example.com/feedback/invite/{self.cycle_a.invitation_token_peer}/', links['message'])
        self.assertIn(f'/feedback/invite/{self.cycle_a.invitation_token_manager}/', links['message'])
        self.cycle_a.refresh_from_db()
        self.assertIsNone(self.cycle_a.links_email_queued_at)

    @patch(SEND_MAIL)
    def test_a_failure_is_recorded_on_the_cycle_and_tried_again(self, send):
        self.cycle_a.include_self = False
        self.cycle_a.save()
        queue_reviewee_notifications(self.cycle_a)
        send.side_effect = ConnectionRefusedError('Connection refused')

        with self.assertLogs('reviews.outbox', level='ERROR'):
            stats = send_queued_emails()

        self.cycle_a.refresh_from_db()
        self.assertIsNotNone(self.cycle_a.links_email_queued_at)
        self.assertEqual(self.cycle_a.links_email_error, 'ConnectionRefusedError: Connection refused')
        self.assertEqual(self.cycle_a.links_email_attempts, 1)
        self.assertEqual(stats['errors'], ['Failed to send the links to alice@example.com: ConnectionRefusedError: Connection refused'])

        send.side_effect = None
        send_queued_emails()

        self.cycle_a.refresh_from_db()
        self.assertIsNone(self.cycle_a.links_email_queued_at)
        self.assertEqual((self.cycle_a.links_email_error, self.cycle_a.links_email_attempts), ('', 0))

    @patch(SEND_MAIL)
    def test_a_closed_cycle_sends_no_links(self, send):
        queue_reviewee_notifications(self.cycle_a)
        ReviewCycle.objects.filter(pk=self.cycle_a.pk).update(status='completed')

        send_queued_emails()

        send.assert_not_called()
        self.cycle_a.refresh_from_db()
        self.assertIsNone(self.cycle_a.links_email_queued_at)


class CommandTests(OutboxTestCase):
    @patch(SEND_MAIL)
    def test_records_a_run_that_sent_something(self, send):
        queue_invitations(ReviewerToken.objects.filter(
            pk=ReviewerTokenFactory(cycle=self.cycle_a, reviewer_email='carol@example.com').pk))
        out = StringIO()

        call_command('send_queued_invitations', stdout=out)

        [run] = CronRun.objects.filter(command='send_queued_invitations')
        self.assertEqual((run.sent, run.errors), (1, ''))
        self.assertIn('Emails sent: 1', out.getvalue())

    def test_an_idle_run_leaves_no_record(self):
        call_command('send_queued_invitations', stdout=StringIO())

        self.assertFalse(CronRun.objects.exists())
