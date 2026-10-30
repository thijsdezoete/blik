"""user_passes_test sent logged-in users who are not superusers to the
login page, which sends logged-in users back to `next`: a redirect loop."""
from django.contrib.auth.models import User
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin
from core.models import Organization
from subscriptions.utils import entitlement, purchased_credits


class SuperuserCreateOrganizationTests(TestCase):
    def test_org_admin_is_sent_to_the_dashboard(self):
        org = Organization.objects.create(name='Acme', email='org@acme.example')
        admin = User.objects.create_user(username='admin', email='a@acme.example', password='pw')
        UserProfile.objects.create(user=admin, organization=org)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        resp = self.client.get(reverse('superuser_create_organization'))

        self.assertRedirects(resp, reverse('admin_dashboard'), fetch_redirect_response=False)


BILLING = dict(STRIPE_SECRET_KEY='sk_test_x', STRIPE_WEBHOOK_SECRET='whsec_x', STRIPE_PRICE_ID_SAAS='price_saas')


@patch('blik.superuser_views.send_welcome_email')
class GrantCreditsTests(TestCase):
    def setUp(self):
        root = User.objects.create_superuser(username='root', email='root@example.com', password='pw')
        # A finished setup, or the middleware sends every request to the setup wizard.
        UserProfile.objects.create(user=root, organization=Organization.objects.create(name='Platform'))
        self.client.force_login(root)

    def create(self, credits):
        self.client.post(reverse('superuser_create_organization'),
                         {'org_name': 'Trial Co', 'admin_email': 'boss@trial.example', 'credits': credits})
        return Organization.objects.filter(name='Trial Co').first()

    @override_settings(**BILLING)
    def test_granted_credits_make_it_a_credits_customer(self, _email):
        org = self.create('7')
        self.assertEqual(entitlement(org), 'credits')
        self.assertEqual(purchased_credits(org), 7)

    @override_settings(**BILLING)
    def test_without_credits_it_has_no_limits(self, _email):
        org = self.create('')
        self.assertIsNotNone(org)
        self.assertEqual(entitlement(org), 'self_hosted')

    @override_settings(**BILLING)
    def test_a_bad_number_creates_nothing(self, _email):
        self.assertIsNone(self.create('-3'))

    @override_settings(STRIPE_SECRET_KEY='')
    def test_without_billing_credits_are_ignored(self, _email):
        org = self.create('7')
        self.assertIsNotNone(org)
        self.assertEqual(entitlement(org), 'self_hosted')
