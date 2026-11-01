from unittest.mock import patch

from django.contrib.admin.sites import site
from django.test import RequestFactory, TestCase

from core.factories import OrganizationFactory, UserFactory

from .admin import CronRunAdmin
from .log import record_run, send_logged
from .models import CronRun, EmailLog

EMAIL = dict(subject='Hi', message='Hi', recipient_list=['admin@example.com'])


class SendLoggedTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()

    def test_logs_a_sent_email(self):
        self.assertEqual(send_logged(self.org, 'welcome', **EMAIL), 1)

        entry = EmailLog.objects.get()
        self.assertEqual((entry.organization, entry.kind, entry.recipient, entry.error),
                         (self.org, 'welcome', 'admin@example.com', ''))

    def test_logs_a_failed_email_and_still_raises(self):
        with patch('notifications.log.send_email', side_effect=OSError('smtp down')):
            with self.assertRaises(OSError):
                send_logged(self.org, 'welcome', **EMAIL)

        self.assertEqual(EmailLog.objects.get().error, 'smtp down')

    def test_the_log_goes_with_the_organization(self):
        send_logged(self.org, 'welcome', **EMAIL)
        self.org.delete()
        self.assertFalse(EmailLog.objects.exists())


class CronRunAdminTests(TestCase):
    def test_lists_only_runs_that_tried_to_send(self):
        record_run('send_trial_reminders', 0, [])
        sent = record_run('send_trial_reminders', 2, [])
        failed = record_run('send_lifecycle_emails', 0, ['smtp down'])

        request = RequestFactory().get('/')
        request.user = UserFactory(is_superuser=True, is_staff=True)
        listed = CronRunAdmin(CronRun, site).get_queryset(request)

        self.assertCountEqual(listed, [sent, failed])
