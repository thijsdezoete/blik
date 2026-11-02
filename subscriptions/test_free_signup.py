from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.factories import UserProfileFactory
from core.factories import UserFactory
from core.models import Organization
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle
from subscriptions.test_billing import BILLING
from subscriptions.utils import NoCycleCredits, cycle_credits, entitlement


@override_settings(**BILLING, RATELIMIT_ENABLE=False)
class FreeSignupTests(TestCase):
    def setUp(self):
        UserProfileFactory()  # past the setup wizard

    def signup(self, email='new@example.com'):
        return self.client.post(reverse('register'), {'email': email})

    def test_signup_gives_one_review_cycle_then_blocks(self):
        response = self.signup(email='New@Example.com')
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        org = Organization.objects.get(name='new@example.com')
        self.assertEqual(entitlement(org), 'credits')
        self.assertEqual(cycle_credits(org), 1)
        self.assertEqual(mail.outbox[0].to, ['new@example.com'])

        reviewee = org.reviewees.get()  # a UserProfile auto-creates one (accounts/signals.py)
        questionnaire = QuestionnaireFactory(organization=org)
        ReviewCycle.objects.create(reviewee=reviewee, questionnaire=questionnaire)
        with self.assertRaises(NoCycleCredits):
            ReviewCycle.objects.create(reviewee=reviewee, questionnaire=questionnaire)

    def test_existing_email_gets_a_notice_not_a_second_organization(self):
        UserFactory(email='taken@example.com', username='taken@example.com')
        orgs = Organization.objects.count()
        response = self.signup(email='TAKEN@example.com')
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertEqual(Organization.objects.count(), orgs)
        self.assertEqual(mail.outbox[0].to, ['taken@example.com'])
        self.assertIn('already has a Blik360 account', mail.outbox[0].body)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_self_hosted_has_no_free_signup(self):
        self.signup()
        self.assertFalse(Organization.objects.filter(name='new@example.com').exists())
