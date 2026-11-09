import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin
from reviews.factories import ReviewCycleFactory

from .models import Report
from .pdf import pdf_filename, store_report_pdf, stored_pdf_bytes
from .services import generate_report


@override_settings(LANGUAGE_CODE='en')
class ReportPdfViewTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        render = mock.patch('reports.pdf.render_report_pdf', side_effect=lambda r, language: b'%PDF ' + language.encode())
        render.start()
        self.addCleanup(render.stop)
        # views.py holds its own reference to the function
        view_render = mock.patch('reports.views.render_report_pdf', side_effect=lambda r, language: b'%PDF ' + language.encode())
        view_render.start()
        self.addCleanup(view_render.stop)

        self.cycle = ReviewCycleFactory(status='completed')
        self.organization = self.cycle.reviewee.organization
        self.report = generate_report(self.cycle)
        # Without a user and an organization, the setup middleware redirects every request
        self.admin_user = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin_user, organization=self.organization)
        self.token_url = reverse('reports:reviewee_report_pdf', args=[self.report.access_token])
        self.admin_url = reverse('reports:report_pdf', args=[self.cycle.uuid])

    def admin(self):
        user = self.admin_user
        assign_organization_admin(user)
        self.client.force_login(user)
        return user

    def test_reviewee_pdf_expired_token_403(self):
        Report.objects.filter(pk=self.report.pk).update(access_token_expires=timezone.now() - timedelta(days=1))
        self.assertEqual(self.client.get(self.token_url).status_code, 403)
        self.assertEqual(self.client.post(self.token_url).status_code, 403)

    def test_reviewee_pdf_cycle_not_completed(self):
        self.cycle.status = 'active'
        self.cycle.save()
        response = self.client.post(self.token_url)
        self.assertTemplateUsed(response, 'reports/report_not_ready.html')
        self.report.refresh_from_db()
        self.assertFalse(self.report.pdf_file)

    def test_reviewee_pdf_serves_stored_file(self):
        store_report_pdf(self.report)
        count = Report.objects.get(pk=self.report.pk).access_count
        response = self.client.get(self.token_url)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(pdf_filename(self.report), response['Content-Disposition'])
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(Report.objects.get(pk=self.report.pk).access_count, count + 1)

    def test_expired_pdf_redirects_to_page(self):
        store_report_pdf(self.report)
        Report.objects.filter(pk=self.report.pk).update(pdf_generated_at=timezone.now() - timedelta(days=400))
        response = self.client.get(self.token_url)
        self.assertRedirects(
            response, reverse('reports:reviewee_report', args=[self.report.access_token]),
            fetch_redirect_response=False,
        )

    def test_post_regenerates_and_serves(self):
        response = self.client.post(self.token_url)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.report.refresh_from_db()
        self.assertTrue(self.report.has_valid_pdf())

    def test_admin_pdf_requires_permission(self):
        self.assertEqual(self.client.get(self.admin_url).status_code, 302)  # to login
        stranger = User.objects.create_user(username='x', email='x@other.example', password='pw')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.admin_url).status_code, 404)

    def test_admin_pdf_owner_goes_to_token_url(self):
        user = self.admin()
        user.email = self.cycle.reviewee.email
        user.save()
        user.user_permissions.clear()
        user.groups.clear()
        self.assertRedirects(self.client.get(self.admin_url), self.token_url, fetch_redirect_response=False)

    def test_reviewee_pdf_in_another_language_is_a_fresh_render(self):
        """A reader of the report page in another language gets the PDF in that language."""
        with mock.patch('reports.views.reviewee_language', return_value='de'), \
                mock.patch('reports.pdf.reviewee_language', return_value='de'):
            store_report_pdf(self.report)
            response = self.client.get(self.token_url)
        self.assertEqual(response.content, b'%PDF en')
        self.report.refresh_from_db()
        self.assertEqual(stored_pdf_bytes(self.report), b'%PDF de')

    def test_admin_pdf_other_language_not_stored(self):
        self.admin()
        with mock.patch('reports.views.reviewee_language', return_value='de'):
            response = self.client.post(self.admin_url)
        self.assertEqual(response.content, b'%PDF en')
        self.report.refresh_from_db()
        self.assertFalse(self.report.pdf_file)

    def test_admin_pdf_in_reviewee_language_is_stored(self):
        self.admin()
        with mock.patch('reports.views.reviewee_language', return_value='en'):
            self.client.post(self.admin_url)
        self.report.refresh_from_db()
        self.assertTrue(self.report.has_valid_pdf())

    def test_regenerate_report_drops_stored_pdf(self):
        store_report_pdf(self.report)
        generate_report(self.cycle)
        self.report.refresh_from_db()
        self.assertFalse(self.report.pdf_file)
        self.assertIsNone(self.report.pdf_generated_at)
