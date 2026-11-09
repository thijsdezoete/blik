"""The PDF of a report over the API: its fields on the report, the download, and the rebuild after regenerate."""
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin
from api.models import APIToken
from reports.models import Report
from reports.pdf import pdf_filename, store_report_pdf
from reports.services import generate_report
from reviews.factories import ReviewCycleFactory


@override_settings(LANGUAGE_CODE='en', SITE_PROTOCOL='https', SITE_DOMAIN='blik.example')
class ReportPdfApiTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        render = mock.patch('reports.pdf.render_report_pdf', return_value=b'%PDF-1.7 test')
        render.start()
        self.addCleanup(render.stop)

        self.cycle = ReviewCycleFactory(status='completed')
        organization = self.cycle.reviewee.organization
        self.report = generate_report(self.cycle)
        admin = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=admin, organization=organization)
        assign_organization_admin(admin)
        token = APIToken.objects.create(organization=organization, created_by=admin, name='Token')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.raw_token}')
        self.url = f'/api/v1/reports/{self.report.uuid}/'

    def test_report_has_pdf_fields(self):
        store_report_pdf(self.report)

        data = self.client.get(self.url).data

        self.assertEqual(data['pdf_url'], f'https://blik.example{self.url}pdf/')
        self.assertIsNotNone(data['pdf_generated_at'])
        self.assertIsNotNone(data['pdf_expires_at'])

    def test_pdf_fields_null_without_stored_pdf(self):
        data = self.client.get(self.url).data

        self.assertIsNone(data['pdf_generated_at'])
        self.assertIsNone(data['pdf_expires_at'])

    def test_pdf_url_null_for_unavailable_report(self):
        Report.objects.filter(pk=self.report.pk).update(available=False)

        self.assertIsNone(self.client.get(self.url).data['pdf_url'])

    def test_pdf_download_serves_stored_file(self):
        store_report_pdf(self.report)

        response = self.client.get(f'{self.url}pdf/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'], f'attachment; filename="{pdf_filename(self.report)}"')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_pdf_download_builds_missing_file(self):
        self.assertFalse(self.report.has_valid_pdf())

        response = self.client.get(f'{self.url}pdf/')

        self.assertTrue(response.content.startswith(b'%PDF'))
        self.report.refresh_from_db()
        self.assertTrue(self.report.has_valid_pdf())

    def test_pdf_download_follows_report_visibility(self):
        other = ReviewCycleFactory(status='completed')
        report = generate_report(other)

        self.assertEqual(self.client.get(f'/api/v1/reports/{report.uuid}/pdf/').status_code, 404)

    def test_regenerate_leaves_a_valid_pdf(self):
        store_report_pdf(self.report)

        response = self.client.post(f'{self.url}regenerate/')

        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.assertTrue(self.report.has_valid_pdf())
        self.assertIsNotNone(response.data['pdf_generated_at'])

    def test_list_filters_by_cycle_uuid(self):
        other = generate_report(ReviewCycleFactory(
            status='completed', reviewee__organization=self.cycle.reviewee.organization,
        ))

        results = self.client.get('/api/v1/reports/', {'cycle__uuid': str(other.cycle.uuid)}).data['results']

        self.assertEqual([r['uuid'] for r in results], [str(other.uuid)])
