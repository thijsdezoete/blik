"""Stripe webhook / checkout tests.

Regression: stripe-python >= 8 returns StripeObject instances that are no
longer dict subclasses (no .get()/.keys()), and recent API versions put
current_period_* on the subscription item instead of the subscription.
The webhook crashed with 500 on every event, so paying customers never got
an account or a welcome email (GitHub #21).
"""
from unittest.mock import patch

import stripe
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import Organization
from subscriptions.models import Plan, Subscription


def _event():
    return stripe.Event.construct_from({
        'id': 'evt_1', 'type': 'checkout.session.completed',
        'data': {'object': {
            'id': 'cs_1', 'mode': 'subscription', 'customer': 'cus_1', 'subscription': 'sub_1',
            'status': 'complete', 'payment_status': 'paid',
            'customer_details': {'email': 'buyer@example.com', 'name': 'Buyer Inc'},
            'metadata': {'plan_type': 'saas'},
        }},
    }, 'sk_test')


def _subscription():
    return stripe.Subscription.construct_from({
        'id': 'sub_1', 'status': 'active', 'created': 1_700_000_000,
        'cancel_at_period_end': False,
        'items': {'data': [{'current_period_start': 1_700_000_000,
                            'current_period_end': 1_702_592_000}]},
    }, 'sk_test')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   STRIPE_WEBHOOK_SECRET='whsec_test')
class StripeWebhookTests(TestCase):
    def setUp(self):
        Plan.objects.create(name='EU SaaS', plan_type='saas', price_monthly=49, max_employees=50)

    @patch('subscriptions.views.stripe.Subscription.retrieve', return_value=_subscription())
    @patch('subscriptions.views.stripe.Webhook.construct_event', return_value=_event())
    def test_checkout_completed_creates_account(self, *_):
        with patch('core.email.send_email') as send:
            resp = self.client.post('/api/stripe/webhook/', data=b'{}',
                                    content_type='application/json',
                                    HTTP_STRIPE_SIGNATURE='sig')
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(email='buyer@example.com')
        org = Organization.objects.get(email='buyer@example.com')
        sub = Subscription.objects.get(stripe_subscription_id='sub_1')
        self.assertEqual(sub.organization, org)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.current_period_end.timestamp(), 1_702_592_000)
        self.assertEqual(send.call_args.kwargs['recipient_list'], [user.email])

    @patch('subscriptions.views.stripe.Webhook.construct_event')
    def test_subscription_updated_reads_period_from_items(self, construct):
        self.test_checkout_completed_creates_account()
        updated = _subscription()
        updated['status'] = 'past_due'
        updated['items']['data'][0]['current_period_end'] = 1_705_000_000
        construct.return_value = stripe.Event.construct_from(
            {'id': 'evt_2', 'type': 'customer.subscription.updated',
             'data': {'object': updated.to_dict()}}, 'sk_test')
        resp = self.client.post('/api/stripe/webhook/', data=b'{}',
                                content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')
        self.assertEqual(resp.status_code, 200)
        sub = Subscription.objects.get(stripe_subscription_id='sub_1')
        self.assertEqual(sub.status, 'past_due')
        self.assertEqual(sub.current_period_end.timestamp(), 1_705_000_000)
