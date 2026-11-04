"""Which account changes send a security notice, and to which address."""
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.factories import UserProfileFactory
from accounts.models import PasswordResetToken
from core.factories import OrganizationFactory, UserFactory


class SecurityNoticeTests(TestCase):
    def setUp(self):
        self.user = UserFactory(username='member', email='old@example.com')
        self.user.set_password('old-pass-123')
        self.user.save()
        UserProfileFactory(user=self.user, organization=OrganizationFactory())

    def edit_profile(self, email):
        self.client.force_login(self.user)
        return self.client.post(reverse('profile'), {
            'first_name': self.user.first_name, 'last_name': self.user.last_name,
            'email': email, 'language': '',
        })

    def test_password_change_on_the_profile_notifies_the_user(self):
        self.client.force_login(self.user)
        self.client.post(reverse('profile'), {
            'change_password': '',
            'old_password': 'old-pass-123',
            'new_password1': 'N3w-strong-passphrase',
            'new_password2': 'N3w-strong-passphrase',
        })

        self.assertEqual([m.to for m in mail.outbox], [['old@example.com']])

    def test_rejected_password_change_sends_nothing(self):
        self.client.force_login(self.user)
        self.client.post(reverse('profile'), {
            'change_password': '', 'old_password': 'wrong',
            'new_password1': 'N3w-strong-passphrase', 'new_password2': 'N3w-strong-passphrase',
        })

        self.assertEqual(mail.outbox, [])

    def test_password_reset_notifies_the_user(self):
        token = PasswordResetToken.objects.create(user=self.user)

        self.client.post(reverse('reset_password', args=[token.token]), {
            'password1': 'N3w-strong-passphrase', 'password2': 'N3w-strong-passphrase',
        })

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('N3w-strong-passphrase'))
        self.assertEqual([m.to for m in mail.outbox], [['old@example.com']])

    def test_email_change_notifies_the_old_address(self):
        self.edit_profile('new@example.com')

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertEqual([m.to for m in mail.outbox], [['old@example.com']])

    def test_profile_edit_without_a_new_email_sends_nothing(self):
        self.edit_profile('OLD@example.com')

        self.assertEqual(mail.outbox, [])

    def test_a_failing_notice_does_not_undo_the_change(self):
        with patch('core.email.send_email', side_effect=OSError('smtp down')):
            self.edit_profile('new@example.com')

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
