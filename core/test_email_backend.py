"""Tests for `core.email`.

The organization's SMTP settings take priority, but when they are absent the
fallback must be the backend from Django settings — not a hardcoded SMTP
connection. Hardcoding SMTP means the console backend never prints and the
locmem backend never fills mail.outbox, so email fails in dev and in tests
regardless of EMAIL_BACKEND.
"""
from unittest.mock import Mock

from django.core import mail
from django.core.mail.backends.locmem import EmailBackend as LocmemBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.test import TestCase, override_settings

from core.email import get_email_backend, send_email
from core.factories import OrganizationFactory


class GetEmailBackendTests(TestCase):
    def test_falls_back_to_configured_backend_when_org_has_no_smtp_host(self):
        OrganizationFactory(smtp_host='')

        # Tests run under the locmem backend; a hardcoded SMTP backend here
        # would try to open a socket to EMAIL_HOST.
        self.assertIsInstance(get_email_backend(), LocmemBackend)

    def test_organization_smtp_settings_take_priority(self):
        OrganizationFactory(smtp_host='smtp.acme.example.com', smtp_port=2525)

        backend = get_email_backend()

        self.assertIsInstance(backend, SMTPBackend)
        self.assertEqual(backend.host, 'smtp.acme.example.com')
        self.assertEqual(backend.port, 2525)

    @override_settings(DEFAULT_FROM_EMAIL='fallback@example.com')
    def test_send_email_delivers_through_configured_backend(self):
        OrganizationFactory(smtp_host='', from_email='org@example.com')

        sent = send_email(
            subject='Hello',
            message='Body',
            recipient_list=['someone@example.com'],
        )

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['someone@example.com'])
        self.assertEqual(mail.outbox[0].from_email, 'org@example.com')

    def test_send_email_uses_the_connection_it_is_given(self):
        """A batch (the outbox cron) passes one open connection to every send instead of
        opening a new SMTP connection per email."""
        OrganizationFactory(smtp_host='smtp.acme.example.com')
        connection = Mock(spec=SMTPBackend)
        connection.send_messages.return_value = 1

        sent = send_email(
            subject='Hello',
            message='Body',
            recipient_list=['someone@example.com'],
            connection=connection,
        )

        self.assertEqual(sent, 1)
        [message] = connection.send_messages.call_args.args[0]
        self.assertEqual(message.to, ['someone@example.com'])
