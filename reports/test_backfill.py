import tempfile
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from notifications.models import SentEmail
from reviews.factories import ReviewCycleFactory

from .models import Report


class BackfillReportPdfsTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        render = mock.patch('reports.pdf.render_report_pdf', side_effect=lambda r, language: b'%PDF ')
        self.render = render.start()
        self.addCleanup(render.stop)
        self.cycle = ReviewCycleFactory(status='completed')

    def run_command(self, *args):
        out = StringIO()
        call_command('backfill_report_pdfs', *args, stdout=out)
        return out.getvalue()

    def test_backfill_creates_report_and_pdf_without_email(self):
        ReviewCycleFactory(status='active')
        self.run_command()

        report = Report.objects.get(cycle=self.cycle)
        self.assertTrue(report.has_valid_pdf())
        self.cycle.refresh_from_db()
        self.assertIsNotNone(self.cycle.report_finalized_at)
        self.assertEqual(Report.objects.count(), 1)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(SentEmail.objects.count(), 0)

    def test_backfill_twice_is_a_no_op(self):
        self.run_command()
        report = Report.objects.get(cycle=self.cycle)
        self.cycle.refresh_from_db()
        pdf_name, finalized_at, generated_at = report.pdf_file.name, self.cycle.report_finalized_at, report.pdf_generated_at
        self.render.reset_mock()

        self.run_command()

        report.refresh_from_db()
        self.cycle.refresh_from_db()
        self.render.assert_not_called()
        self.assertEqual(report.pdf_file.name, pdf_name)
        self.assertEqual(report.pdf_generated_at, generated_at)
        self.assertEqual(self.cycle.report_finalized_at, finalized_at)
        self.assertEqual(mail.outbox, [])

    def test_dry_run_changes_nothing(self):
        self.run_command('--dry-run')
        self.assertFalse(Report.objects.exists())
        self.cycle.refresh_from_db()
        self.assertIsNone(self.cycle.report_finalized_at)

    def test_failing_cycle_is_reported_and_loop_continues(self):
        other = ReviewCycleFactory(status='completed')

        def fail_first(report, language):
            if report.cycle_id == self.cycle.pk:
                raise RuntimeError('boom')
            return b'%PDF '

        self.render.side_effect = fail_first
        out = self.run_command()

        self.assertIn('boom', out)
        self.assertTrue(Report.objects.get(cycle=other).has_valid_pdf())
        self.cycle.refresh_from_db()
        self.assertIsNone(self.cycle.report_finalized_at)
