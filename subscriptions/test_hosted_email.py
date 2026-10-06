from django.test import Client, TestCase
from django.urls import reverse

from accounts.factories import UserProfileFactory
from core.factories import OrganizationFactory, UserFactory
from subscriptions.testing import grant, subscribe


class HostedEmailSetupTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        user = UserFactory()
        UserProfileFactory(user=user, organization=self.org)
        self.client = Client()
        self.client.force_login(user)

    def offered(self):
        return self.client.get(reverse('setup_email')).context['is_hosted']

    def test_self_hosted_organization_is_not_offered_managed_email(self):
        self.assertFalse(self.offered())

    def test_subscriber_is_offered_managed_email(self):
        subscribe(self.org)
        self.assertTrue(self.offered())

    def test_single_round_buyer_is_offered_managed_email_even_at_zero_credits(self):
        grant(self.org, 0)
        self.assertTrue(self.offered())

    def test_single_round_buyer_can_choose_managed_email(self):
        grant(self.org, 0)
        response = self.client.post(reverse('setup_email'), {'use_blik_mailer': 'true'})
        self.assertRedirects(response, reverse('setup_complete'), fetch_redirect_response=False)
