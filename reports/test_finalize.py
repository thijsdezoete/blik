import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin

from notifications.models import CronRun
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory

from .finalize import MAX_PDF_ATTEMPTS, cycles_to_finalize, delete_expired_pdfs, finalize_cycle
from .models import Report
from .pdf import store_report_pdf
from .services import generate_report


@override_settings(LANGUAGE_CODE='en')
class FinalizeReportsTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        render = mock.patch('reports.pdf.render_report_pdf', return_value=b'%PDF-1.7 test')
        render.start()
        self.addCleanup(render.stop)

    def completed_cycle(self, auto_send=True, attach=True):
        cycle = ReviewCycleFactory(status='completed')
        organization = cycle.reviewee.organization
        organization.auto_send_report_email = auto_send
        organization.attach_report_pdf = attach
        organization.save()
        return cycle

    def run_command(self):
        call_command('finalize_reports', stdout=StringIO(), stderr=StringIO())

    def test_new_completed_cycle_gets_report_pdf_and_email(self):
        cycle = self.completed_cycle()

        self.run_command()

        report = Report.objects.get(cycle=cycle)
        self.assertTrue(report.has_valid_pdf())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [cycle.reviewee.email])
        self.assertEqual(mail.outbox[0].attachments[0][1], b'%PDF-1.7 test')
        cycle.refresh_from_db()
        self.assertIsNotNone(cycle.report_finalized_at)
        self.assertEqual(CronRun.objects.get(command='finalize_reports').sent, 1)

    def test_finalized_cycle_is_skipped_on_next_run(self):
        self.completed_cycle()

        self.run_command()
        self.run_command()

        self.assertEqual(len(mail.outbox), 1)

    def test_cycle_completed_before_migration_is_not_emailed(self):
        cycle = self.completed_cycle()
        cycle.report_finalized_at = timezone.now() - timedelta(days=100)
        cycle.save()

        self.run_command()

        self.assertEqual(mail.outbox, [])
        self.assertFalse(Report.objects.filter(cycle=cycle).exists())

    def test_active_cycle_is_not_finalized(self):
        ReviewCycleFactory(status='active')

        self.assertFalse(cycles_to_finalize().exists())

    def test_auto_send_off_finalizes_without_email(self):
        cycle = self.completed_cycle(auto_send=False)

        self.assertEqual(finalize_cycle(cycle)[0], 'finalized')

        self.assertEqual(mail.outbox, [])
        self.assertTrue(Report.objects.get(cycle=cycle).has_valid_pdf())
        self.assertIsNotNone(cycle.report_finalized_at)

    def test_force_send_sends_with_auto_send_off(self):
        cycle = self.completed_cycle(auto_send=False)

        self.assertEqual(finalize_cycle(cycle, force_send=True)[0], 'sent')

        self.assertEqual(len(mail.outbox), 1)

    def test_attach_off_sends_without_pdf(self):
        cycle = self.completed_cycle(attach=False)

        self.assertEqual(finalize_cycle(cycle)[0], 'sent_without_pdf')

        self.assertEqual(mail.outbox[0].attachments, [])
        # The web version still links to a stored PDF
        self.assertTrue(Report.objects.get(cycle=cycle).has_valid_pdf())

    @mock.patch('reports.finalize.store_report_pdf', side_effect=RuntimeError('render failed'))
    def test_pdf_failure_waits_then_sends_link_only_after_three_attempts(self, _store):
        cycle = self.completed_cycle()

        with self.assertLogs('reports.finalize', 'ERROR'):
            self.assertEqual(finalize_cycle(cycle)[0], 'waiting_for_pdf')
            self.assertEqual(finalize_cycle(cycle)[0], 'waiting_for_pdf')
        self.assertEqual(mail.outbox, [])
        cycle.refresh_from_db()
        self.assertIsNone(cycle.report_finalized_at)

        with self.assertLogs('reports.finalize', 'ERROR'):
            self.assertEqual(finalize_cycle(cycle)[0], 'sent_without_pdf')

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments, [])
        self.assertEqual(Report.objects.get(cycle=cycle).pdf_attempts, 3)
        self.assertIsNotNone(cycle.report_finalized_at)

    @mock.patch('reports.finalize.store_report_pdf', side_effect=RuntimeError('render failed'))
    def test_force_send_does_not_wait_for_the_pdf(self, _store):
        cycle = self.completed_cycle()

        with self.assertLogs('reports.finalize', 'ERROR'):
            self.assertEqual(finalize_cycle(cycle, force_send=True)[0], 'sent_without_pdf')

        self.assertEqual(len(mail.outbox), 1)

    def test_failed_email_is_retried_with_its_errors(self):
        cycle = self.completed_cycle()

        with mock.patch('reports.finalize.send_report_ready_notification',
                        return_value={'sent': 0, 'errors': ['SMTP down']}), \
                self.assertLogs('reports.finalize', 'ERROR'):
            self.assertEqual(finalize_cycle(cycle), ('failed', ['SMTP down']))

        cycle.refresh_from_db()
        self.assertIsNone(cycle.report_finalized_at)

    def test_reviewee_without_email_is_retried_without_a_cron_error(self):
        cycle = self.completed_cycle()
        cycle.reviewee.email = ''
        cycle.reviewee.save()

        with self.assertLogs('reports.finalize', 'WARNING') as logs:
            self.run_command()
            self.run_command()

        self.assertEqual([r.levelname for r in logs.records], ['WARNING', 'WARNING'])
        cycle.refresh_from_db()
        self.assertIsNone(cycle.report_finalized_at)
        self.assertFalse(CronRun.objects.filter(command='finalize_reports').exists())

    def test_run_that_did_nothing_is_not_recorded(self):
        self.run_command()

        self.assertFalse(CronRun.objects.filter(command='finalize_reports').exists())

    def test_pdf_that_stays_invalid_after_storing_counts_as_failed_attempt(self):
        cycle = self.completed_cycle()

        with mock.patch.object(Report, 'has_valid_pdf', return_value=False), \
                self.assertLogs('reports.finalize', 'ERROR'):
            self.assertEqual(finalize_cycle(cycle)[0], 'waiting_for_pdf')

        self.assertEqual(Report.objects.get(cycle=cycle).pdf_attempts, 1)

    def test_regenerated_report_gets_its_pdf_attempts_again(self):
        cycle = self.completed_cycle()
        report = generate_report(cycle)
        Report.objects.filter(pk=report.pk).update(pdf_attempts=MAX_PDF_ATTEMPTS)

        report = generate_report(cycle)

        report.refresh_from_db()
        self.assertEqual(report.pdf_attempts, 0)

    def test_one_failing_cycle_does_not_block_others(self):
        failing = self.completed_cycle()
        other = self.completed_cycle()
        real_generate = generate_report

        def generate(cycle):
            if cycle.pk == failing.pk:
                raise RuntimeError('boom')
            return real_generate(cycle)

        with mock.patch('reports.finalize.generate_report', side_effect=generate), \
                self.assertLogs('reports.finalize', 'ERROR'):
            self.run_command()

        self.assertEqual([m.to for m in mail.outbox], [[other.reviewee.email]])
        failing.refresh_from_db()
        self.assertIsNone(failing.report_finalized_at)
        self.assertIn('boom', CronRun.objects.get(command='finalize_reports').errors)

    def test_report_from_before_the_last_submission_is_regenerated(self):
        cycle = self.completed_cycle()
        report = generate_report(cycle)
        Report.objects.filter(pk=report.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        ReviewerTokenFactory(cycle=cycle, completed_at=timezone.now())

        with mock.patch('reports.finalize.generate_report', wraps=generate_report) as regenerate:
            finalize_cycle(cycle)

        regenerate.assert_called_once_with(cycle)
        # So the next run keeps it
        report.refresh_from_db()
        self.assertGreater(report.updated_at, cycle.tokens.get().completed_at)

    def test_current_report_is_kept(self):
        cycle = self.completed_cycle()
        ReviewerTokenFactory(cycle=cycle, completed_at=timezone.now() - timedelta(hours=1))
        generate_report(cycle)

        with mock.patch('reports.finalize.generate_report') as regenerate:
            finalize_cycle(cycle)

        regenerate.assert_not_called()

    def test_delete_expired_pdfs(self):
        expired = generate_report(self.completed_cycle())
        store_report_pdf(expired)
        fresh = generate_report(self.completed_cycle())
        store_report_pdf(fresh)
        expired_name = expired.pdf_file.name
        Report.objects.filter(pk=expired.pk).update(
            pdf_generated_at=timezone.now() - timedelta(days=400))

        self.assertEqual(delete_expired_pdfs(), 1)

        expired.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(expired.pdf_file.name, '')
        self.assertIsNone(expired.pdf_generated_at)
        self.assertFalse(fresh.pdf_file.storage.exists(expired_name))
        self.assertTrue(fresh.has_valid_pdf())

    def test_admin_close_sends_now_and_cron_does_not_send_again(self):
        cycle = self.completed_cycle(auto_send=False)
        cycle.status = 'active'
        cycle.save()
        ReviewerTokenFactory(cycle=cycle, completed_at=timezone.now())
        admin = User.objects.create_user(username='admin')
        UserProfile.objects.create(user=admin, organization=cycle.reviewee.organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        self.client.post(reverse('close_cycle', args=[cycle.uuid]))
        self.run_command()

        self.assertEqual([m.to for m in mail.outbox if m.to == [cycle.reviewee.email]], [[cycle.reviewee.email]])
        cycle.refresh_from_db()
        self.assertEqual(cycle.status, 'completed')
        self.assertIsNotNone(cycle.report_finalized_at)


@override_settings(LANGUAGE_CODE='en')
class AdminReportEmailMessageTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        render = mock.patch('reports.pdf.render_report_pdf', return_value=b'%PDF-1.7 test')
        render.start()
        self.addCleanup(render.stop)

        self.cycle = ReviewCycleFactory(status='completed', reviewee__name='Anna de Vries')
        # A profile makes a reviewee for its user too, so the admin needs an address of their own
        admin = User.objects.create_user(username='admin', email='admin@example.org')
        UserProfile.objects.create(user=admin, organization=self.cycle.reviewee.organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

    def messages(self, response):
        return [str(m) for m in response.context['messages']]

    def without_email(self):
        self.cycle.reviewee.email = ''
        self.cycle.reviewee.save()

    def generate(self):
        return self.client.get(reverse('generate_report', args=[self.cycle.uuid]), follow=True)

    def send(self):
        generate_report(self.cycle)
        return self.client.post(reverse('send_report_email', args=[self.cycle.uuid]), follow=True)

    def test_generate_report_says_email_sent(self):
        self.assertEqual(self.messages(self.generate()),
                         ['Report generated successfully for Anna de Vries. Notification email sent.'])

    def test_generate_report_shows_the_email_errors(self):
        self.without_email()

        self.assertEqual(self.messages(self.generate()), [
            'Report generated successfully for Anna de Vries. '
            '(Email errors: No email address for reviewee Anna de Vries)'])

    def test_send_report_email_says_sent(self):
        email = self.cycle.reviewee.email

        self.assertEqual(self.messages(self.send()), [f'Report email sent to Anna de Vries at {email}.'])

    def test_send_report_email_shows_each_error(self):
        self.without_email()

        self.assertEqual(self.messages(self.send()),
                         ['Failed to send email: No email address for reviewee Anna de Vries'])
