from unittest import mock

from django.test import SimpleTestCase

from reports.checks import pdf_engine_check


class PdfEngineCheckTests(SimpleTestCase):
    def test_pdf_engine_check_passes(self):
        self.assertEqual(pdf_engine_check(None), [])

    def test_pdf_engine_check_reports_error_when_render_fails(self):
        with mock.patch('weasyprint.HTML', side_effect=OSError('no pango')):
            errors = pdf_engine_check(None)
        self.assertEqual([e.id for e in errors], ['reports.E001'])
