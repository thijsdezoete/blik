from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin
from core.models import Organization

from reports.models import Report
from reports.storage import private_storage
from reviews.factories import ReviewCycleFactory


class ReportPdfRetentionTests(TestCase):
    def make_report(self, retention=None, generated_ago=timedelta(days=1), name='report_pdfs/x.pdf'):
        cycle = ReviewCycleFactory()
        org = cycle.reviewee.organization
        org.report_pdf_retention_days = retention
        org.save()
        return Report(
            cycle=cycle,
            report_data={},
            pdf_file=name,
            pdf_generated_at=timezone.now() - generated_ago,
        )

    @override_settings(REPORT_PDF_RETENTION_DAYS=30)
    def test_pdf_expiry_uses_org_then_env_default(self):
        report = self.make_report(retention=None)
        self.assertEqual(report.pdf_retention_days, 30)
        self.assertEqual(report.pdf_expires_at, report.pdf_generated_at + timedelta(days=30))

        report = self.make_report(retention=7)
        self.assertEqual(report.pdf_retention_days, 7)
        self.assertEqual(report.pdf_expires_at, report.pdf_generated_at + timedelta(days=7))

    def test_pdf_expires_at_none_without_pdf(self):
        report = Report(cycle=ReviewCycleFactory(), report_data={})
        self.assertIsNone(report.pdf_expires_at)

    def test_has_valid_pdf_true_when_present_and_fresh(self):
        report = self.make_report(retention=7)
        with mock.patch.object(private_storage, 'exists', return_value=True):
            self.assertTrue(report.has_valid_pdf())

    def test_has_valid_pdf_false_when_expired(self):
        report = self.make_report(retention=7, generated_ago=timedelta(days=8))
        with mock.patch.object(private_storage, 'exists', return_value=True):
            self.assertFalse(report.has_valid_pdf())

    def test_has_valid_pdf_false_when_file_missing_on_disk(self):
        report = self.make_report(retention=7, name='report_pdfs/does-not-exist.pdf')
        self.assertFalse(report.has_valid_pdf())

    def test_has_valid_pdf_false_without_file(self):
        report = self.make_report(retention=7, name='')
        self.assertFalse(report.has_valid_pdf())


class PrivateStorageTests(TestCase):
    def test_private_storage_has_no_url(self):
        with self.assertRaises(ValueError):
            private_storage.url('report_pdfs/x.pdf')


class ReportSettingsFormTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')
        admin = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=admin, organization=self.org)
        assign_organization_admin(admin)
        self.client.force_login(admin)

    def post(self, **data):
        self.client.post(reverse('settings'), {'section': 'reports', 'min_responses_for_anonymity': '3', **data})
        self.org.refresh_from_db()

    def test_retention_saved(self):
        self.post(report_pdf_retention_days='14')
        self.assertEqual(self.org.report_pdf_retention_days, 14)

    def test_blank_retention_means_default(self):
        self.org.report_pdf_retention_days = 14
        self.org.save()
        self.post(report_pdf_retention_days='')
        self.assertIsNone(self.org.report_pdf_retention_days)

    def test_invalid_retention_keeps_current_value(self):
        self.org.report_pdf_retention_days = 14
        self.org.save()
        for bad in ('0', '-3', 'abc'):
            self.post(report_pdf_retention_days=bad)
            self.assertEqual(self.org.report_pdf_retention_days, 14)

    def test_attach_checkbox(self):
        self.post(attach_report_pdf='on')
        self.assertTrue(self.org.attach_report_pdf)
        self.post()
        self.assertFalse(self.org.attach_report_pdf)
