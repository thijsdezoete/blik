"""A deletion the user asks for is confirmed by email, to the address it had before."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin
from core.models import Organization
from subscriptions.testing import subscribe


class DeletionConfirmationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')
        self.admin = User.objects.create_user(username='admin', email='a@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

    def test_deleting_an_account_confirms_it_to_its_address(self):
        member = User.objects.create_user(username='member', email='m@acme.example', password='pw')
        UserProfile.objects.create(user=member, organization=self.org)
        self.client.force_login(member)

        self.client.post(reverse('account:delete_account'), {'password': 'pw'})

        self.assertFalse(User.objects.filter(pk=member.pk).exists())
        self.assertEqual([m.to for m in mail.outbox], [['m@acme.example']])

    def test_refused_deletion_sends_nothing(self):
        self.client.force_login(self.admin)

        self.client.post(reverse('account:delete_account'), {'password': 'wrong'})

        self.assertEqual(mail.outbox, [])

    @patch('subscriptions.services.stripe.Subscription.delete')
    def test_deleting_an_organization_confirms_it_once_to_the_admin(self, _):
        subscribe(self.org)
        self.client.force_login(self.admin)

        self.client.post(reverse('account:delete_organization'),
                         {'password': 'pw', 'organization_name': 'Acme'})

        self.assertFalse(Organization.objects.filter(pk=self.org.pk).exists())
        self.assertEqual([m.to for m in mail.outbox], [['a@acme.example']])
