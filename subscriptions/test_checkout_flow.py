from datetime import timedelta
from unittest.mock import patch

import stripe
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.factories import UserProfileFactory
from core.factories import OrganizationFactory, UserFactory
from subscriptions.models import CheckoutFulfilment, OneTimeLoginToken, RoundPurchase
from subscriptions.testing import checkout_session
from subscriptions.utils import cycle_credits


def post_webhook(client, session, event_type='checkout.session.completed'):
    event = stripe.Event.construct_from(
        {'id': 'evt_1', 'type': event_type, 'data': {'object': session}},
        'sk_test',
    )
    with patch('subscriptions.views.stripe.Webhook.construct_event', return_value=event):
        return client.post('/api/stripe/webhook/', data=b'{}',
                           content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')


def open_success_page(client, session):
    stripe_session = stripe.checkout.Session.construct_from(session, 'sk_test')
    with patch('subscriptions.views.stripe.checkout.Session.retrieve',
               return_value=stripe_session):
        return client.get('/api/stripe/checkout-success/', {'session_id': session['id']})


def signed_in_user_id(client):
    return client.session.get('_auth_user_id')


@override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
class CheckoutFlowTests(TestCase):
    def setUp(self):
        patcher = patch('core.email.send_email')
        self.send_email = patcher.start()
        self.addCleanup(patcher.stop)

    def token_url(self, session_id='cs_1'):
        token = OneTimeLoginToken.objects.get(fulfilment__stripe_session_id=session_id)
        return reverse('subscriptions:auto_login', args=[token.token])

    def test_webhook_first_then_success_page_logs_the_new_user_in(self):
        self.assertEqual(post_webhook(self.client, checkout_session()).status_code, 200)
        response = open_success_page(self.client, checkout_session())
        self.assertRedirects(response, self.token_url(), fetch_redirect_response=False)
        self.client.get(response.url)
        user = User.objects.get(email='buyer@example.com')
        self.assertEqual(signed_in_user_id(self.client), str(user.pk))
        self.assertEqual(RoundPurchase.objects.count(), 1)

    def test_success_page_first_then_webhook_gives_the_same_result(self):
        response = open_success_page(self.client, checkout_session())
        self.assertRedirects(response, self.token_url(), fetch_redirect_response=False)
        self.assertEqual(post_webhook(self.client, checkout_session()).status_code, 200)
        self.client.get(response.url)
        user = User.objects.get(email='buyer@example.com')
        self.assertEqual(signed_in_user_id(self.client), str(user.pk))
        self.assertEqual(RoundPurchase.objects.count(), 1)
        self.assertEqual(cycle_credits(user.profile.organization), 10)

    def test_another_checkout_with_the_same_email_cannot_log_in(self):
        post_webhook(self.client, checkout_session())          # creates the account
        stranger = Client()
        response = open_success_page(stranger, checkout_session(id='cs_2'))
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertIsNone(signed_in_user_id(stranger))
        self.assertEqual(OneTimeLoginToken.objects.count(), 1)
        self.assertFalse(OneTimeLoginToken.objects.filter(
            fulfilment__stripe_session_id='cs_2').exists())

    def test_a_token_works_exactly_once(self):
        post_webhook(self.client, checkout_session())
        url = self.token_url()
        self.client.get(url)
        second = Client()
        response = second.get(url)
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertIsNone(signed_in_user_id(second))

    def test_an_expired_token_leads_to_the_login_page(self):
        post_webhook(self.client, checkout_session())
        OneTimeLoginToken.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        response = open_success_page(self.client, checkout_session())
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertIsNone(signed_in_user_id(self.client))

    def test_auto_login_refuses_an_expired_token_itself(self):
        post_webhook(self.client, checkout_session())
        url = self.token_url()
        OneTimeLoginToken.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        response = self.client.get(url)
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertIsNone(signed_in_user_id(self.client))
        self.assertFalse(OneTimeLoginToken.objects.get().used)

    def test_a_signed_in_user_is_never_switched_to_the_new_account(self):
        other = UserFactory()
        UserProfileFactory(user=other, organization=OrganizationFactory())
        self.client.force_login(other)
        post_webhook(Client(), checkout_session())
        response = open_success_page(self.client, checkout_session())
        self.assertRedirects(response, reverse('admin_dashboard'), fetch_redirect_response=False)
        self.client.get(self.token_url())
        self.assertEqual(signed_in_user_id(self.client), str(other.pk))
        self.assertFalse(OneTimeLoginToken.objects.get().used)

    def test_in_app_purchase_keeps_the_admin_signed_in(self):
        org = OrganizationFactory()
        admin = UserFactory()
        UserProfileFactory(user=admin, organization=org)
        self.client.force_login(admin)
        session = checkout_session(client_reference_id=str(org.pk),
                                   metadata={'plan_type': 'single', 'user_id': str(admin.pk)})
        response = open_success_page(self.client, session)
        self.assertRedirects(response, reverse('admin_dashboard'), fetch_redirect_response=False)
        self.assertEqual(signed_in_user_id(self.client), str(admin.pk))
        self.assertEqual(cycle_credits(org), 10)

    def test_a_failed_delivery_returns_500_and_the_retry_fulfils(self):
        with patch('subscriptions.fulfilment.RoundPurchase.objects.create',
                   side_effect=RuntimeError('boom')):
            self.assertEqual(post_webhook(self.client, checkout_session()).status_code, 500)
        self.assertFalse(CheckoutFulfilment.objects.exists())
        self.assertEqual(post_webhook(self.client, checkout_session()).status_code, 200)
        self.assertEqual(RoundPurchase.objects.count(), 1)

    def test_a_failing_welcome_email_still_returns_200_and_is_not_repeated(self):
        self.send_email.side_effect = Exception('smtp down')
        self.assertEqual(post_webhook(self.client, checkout_session()).status_code, 200)
        self.assertEqual(post_webhook(self.client, checkout_session()).status_code, 200)
        self.assertEqual(self.send_email.call_count, 1)
        self.assertEqual(RoundPurchase.objects.count(), 1)

    def test_a_delayed_payment_is_fulfilled_when_it_succeeds(self):
        # Bank debits and transfers complete the session before the money arrives.
        pending = checkout_session(payment_status='unpaid')
        self.assertEqual(post_webhook(self.client, pending).status_code, 200)
        self.assertFalse(CheckoutFulfilment.objects.exists())
        self.assertFalse(User.objects.filter(email='buyer@example.com').exists())

        response = post_webhook(self.client, checkout_session(),
                                event_type='checkout.session.async_payment_succeeded')
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='buyer@example.com')
        self.assertEqual(RoundPurchase.objects.count(), 1)
        self.assertEqual(cycle_credits(user.profile.organization), 10)

    def test_the_success_page_grants_nothing_while_a_payment_is_pending(self):
        response = open_success_page(self.client, checkout_session(payment_status='unpaid'))
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertFalse(CheckoutFulfilment.objects.exists())
        self.assertIsNone(signed_in_user_id(self.client))

    def test_a_session_from_elsewhere_is_acknowledged_and_ignored(self):
        response = post_webhook(self.client, checkout_session(metadata={}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CheckoutFulfilment.objects.exists())

    def test_an_unknown_session_id_leads_to_the_login_page(self):
        with patch('subscriptions.views.stripe.checkout.Session.retrieve',
                   side_effect=Exception('No such checkout.session')):
            response = self.client.get('/api/stripe/checkout-success/', {'session_id': 'cs_nope'})
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_success_page_survives_a_fulfilment_failure(self):
        with patch('subscriptions.views.fulfil_checkout', side_effect=RuntimeError('boom')):
            response = open_success_page(self.client, checkout_session())
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
