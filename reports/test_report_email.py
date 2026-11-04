from unittest.mock import patch

from django.core import mail
from django.test import TestCase

from core.email import send_email
from django.contrib.auth.models import User
from core.models import Organization
from accounts.models import Reviewee
from questionnaires.models import Questionnaire
from reports.pdf import pdf_filename
from reports.services import generate_report, send_report_ready_notification
from reviews.models import ReviewCycle

ATTACHED_LINE = 'The attached PDF holds your full report. Forward it only to people you want to read it.'
LINK_LINE = 'Your report is confidential. The secure link above opens it.'


class ReportEmailAttachmentTests(TestCase):
    def setUp(self):
        org = Organization.objects.create(name='Org', email='org@example.org')
        user = User.objects.create_user(username='admin', email='admin@example.org')
        reviewee = Reviewee.objects.create(
            name='Anna de Vries', email='anna@example.org', organization=org)
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=Questionnaire.objects.create(name='Q', organization=org),
            created_by=user,
            status='completed',
        )
        self.report = generate_report(cycle)

    def test_report_email_attaches_pdf(self):
        send_report_ready_notification(self.report, pdf=b'%PDF-1.7 test')

        message = mail.outbox[0]
        self.assertEqual(
            message.attachments,
            [(pdf_filename(self.report), b'%PDF-1.7 test', 'application/pdf')])
        self.assertIn(ATTACHED_LINE, message.body)
        self.assertNotIn(LINK_LINE, message.body)
        self.assertIn(ATTACHED_LINE, message.alternatives[0][0])

    def test_report_email_without_pdf_keeps_link_only(self):
        send_report_ready_notification(self.report)

        message = mail.outbox[0]
        self.assertEqual(message.attachments, [])
        self.assertIn(LINK_LINE, message.body)
        self.assertNotIn(ATTACHED_LINE, message.body)
        self.assertIn(LINK_LINE, message.alternatives[0][0])


class SendEmailAttachmentTests(TestCase):
    def test_send_email_passes_attachments(self):
        send_email('Subject', 'Body', ['a@example.org'],
                   attachments=[('r.pdf', b'data', 'application/pdf')])

        self.assertEqual(
            mail.outbox[0].attachments, [('r.pdf', b'data', 'application/pdf')])
