"""Deleting an organization removes its users too and copes with a subscription Stripe no longer has."""
from unittest.mock import patch

import stripe
from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import UserProfile
from accounts.services import delete_organization
from core.models import Organization
from subscriptions.testing import subscribe

STRIPE_DELETE = 'subscriptions.services.stripe.Subscription.delete'


class DeleteOrganizationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')
        self.user = User.objects.create_user(username='a@acme.example', email='a@acme.example')
        UserProfile.objects.create(user=self.user, organization=self.org)
        self.outsider = User.objects.create_user(username='o@other.example', email='o@other.example')

    def test_removes_the_users_of_the_organization_only(self):
        delete_organization(self.org)

        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.outsider.pk).exists())

    @patch(STRIPE_DELETE, side_effect=stripe.InvalidRequestError('No such subscription', 'id', code='resource_missing'))
    def test_subscription_missing_in_stripe_does_not_stop_the_deletion(self, _):
        subscribe(self.org)

        delete_organization(self.org)

        self.assertFalse(Organization.objects.filter(pk=self.org.pk).exists())

    @patch(STRIPE_DELETE, side_effect=stripe.InvalidRequestError('Bad key', 'id', code='api_key_invalid'))
    def test_other_stripe_errors_keep_the_organization(self, _):
        subscribe(self.org)

        with self.assertRaises(stripe.InvalidRequestError):
            delete_organization(self.org)

        self.assertTrue(Organization.objects.filter(pk=self.org.pk).exists())
