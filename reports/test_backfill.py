import tempfile
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from api.models import WebhookDelivery, WebhookEndpoint
from notifications.models import SentEmail
from questionnaires.models import Question, QuestionSection
from reviews.factories import ReviewCycleFactory
from reviews.models import Response, ReviewerToken

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
        # A data migration finalised the old cycles
        self.cycle = ReviewCycleFactory(status='completed', report_finalized_at=timezone.now())

    def run_command(self, *args):
        out = StringIO()
        call_command('backfill_report_pdfs', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_backfill_creates_report_and_pdf_without_email(self):
        ReviewCycleFactory(status='active')
        self.run_command()

        report = Report.objects.get(cycle=self.cycle)
        self.assertTrue(report.has_valid_pdf())
        self.cycle.refresh_from_db()
        self.assertEqual(Report.objects.count(), 1)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(SentEmail.objects.count(), 0)

    def test_backfill_twice_is_a_no_op(self):
        self.run_command()
        report = Report.objects.get(cycle=self.cycle)
        self.cycle.refresh_from_db()
        pdf_name, generated_at = report.pdf_file.name, report.pdf_generated_at
        self.render.reset_mock()

        self.run_command()

        report.refresh_from_db()
        self.cycle.refresh_from_db()
        self.render.assert_not_called()
        self.assertEqual(report.pdf_file.name, pdf_name)
        self.assertEqual(report.pdf_generated_at, generated_at)
        self.assertEqual(mail.outbox, [])

    def test_dry_run_changes_nothing(self):
        self.run_command('--dry-run')
        self.assertFalse(Report.objects.exists())

    def test_backfill_skips_unfinalized_cycles(self):
        pending = ReviewCycleFactory(status='completed')
        self.run_command()
        self.assertFalse(Report.objects.filter(cycle=pending).exists())
        pending.refresh_from_db()
        self.assertIsNone(pending.report_finalized_at)

    def test_failing_cycle_is_reported_and_loop_continues(self):
        other = ReviewCycleFactory(status='completed', report_finalized_at=timezone.now())

        def fail_first(report, language):
            if report.cycle_id == self.cycle.pk:
                raise RuntimeError('boom')
            return b'%PDF '

        self.render.side_effect = fail_first
        with self.assertRaises(CommandError):
            self.run_command()

        self.assertTrue(Report.objects.get(cycle=other).has_valid_pdf())

    def add_answers(self):
        questionnaire = self.cycle.questionnaire
        section = QuestionSection.objects.create(questionnaire=questionnaire, title='Craft', order=0)
        self.kept = Question.objects.create(
            section=section, question_text='Kept', question_type='rating', config={'min': 1, 'max': 5},
        )
        self.dropped = Question.objects.create(
            section=section, question_text='Dropped', question_type='rating', order=1, config={'min': 1, 'max': 5},
        )
        token = ReviewerToken.objects.create(cycle=self.cycle, category='self')
        for question in (self.kept, self.dropped):
            Response.objects.create(
                cycle=self.cycle, question=question, token=token, category='self', answer_data={'value': 4},
            )

    def test_regenerate_keeps_a_report_whose_question_was_deleted(self):
        self.add_answers()
        self.run_command()
        stored = Report.objects.get(cycle=self.cycle).report_data
        self.dropped.delete()

        output = self.run_command('--regenerate')

        report = Report.objects.get(cycle=self.cycle)
        self.assertEqual(report.report_data, stored)
        self.assertIn(f'Cycle {self.cycle.pk}', output)
        self.assertTrue(report.has_valid_pdf())

    def test_regenerate_recalculates_a_report_that_lost_nothing(self):
        self.add_answers()
        self.run_command()
        Report.objects.filter(cycle=self.cycle).update(report_data={'by_section': {}})

        self.run_command('--regenerate')

        self.assertTrue(Report.objects.get(cycle=self.cycle).report_data['by_section'])

    def test_a_report_from_an_older_version_is_recalculated_without_the_flag(self):
        """Production holds reports stored before schema 2; the PDF reads keys they lack."""
        self.add_answers()
        self.run_command()
        Report.objects.filter(cycle=self.cycle).update(
            report_data={'by_section': {}, 'insights': {'agency_profile': {'agency_stage': 'Directed'}}},
        )

        output = self.run_command()

        report = Report.objects.get(cycle=self.cycle)
        self.assertEqual(report.report_data['schema'], 2)
        self.assertIn('Reports recalculated: 1 done', output)
        self.assertTrue(report.has_valid_pdf())

    def test_regenerate_fires_no_webhook(self):
        self.add_answers()
        self.run_command()
        endpoint = WebhookEndpoint.objects.create(
            organization=self.cycle.reviewee.organization, name='Hook', url='https://example.com/hook',
            events=['report.generated'], is_active=True,
        )

        self.run_command('--regenerate')

        self.assertFalse(WebhookDelivery.objects.filter(endpoint=endpoint).exists())
