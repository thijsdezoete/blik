import json
from unittest.mock import MagicMock, patch

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.factories import UserProfileFactory
from accounts.permissions import assign_organization_admin
from core.factories import OrganizationFactory, UserFactory
from subscriptions.testing import grant, subscribe
from subscriptions.utils import price_id_for

PRICES = dict(STRIPE_PRICE_ID_SAAS='price_saas', STRIPE_PRICE_ID_ENTERPRISE='price_ent',
              STRIPE_PRICE_ID_SINGLE='price_single')
CREATE = 'subscriptions.views.stripe.checkout.Session.create'
SESSION = MagicMock(id='cs_1', url='https://checkout.stripe.test/cs_1')


@override_settings(**PRICES)
class PriceIdTests(SimpleTestCase):
    def test_known_plan_types_map_to_their_price(self):
        self.assertEqual(price_id_for('saas'), 'price_saas')
        self.assertEqual(price_id_for('enterprise'), 'price_ent')
        self.assertEqual(price_id_for('single'), 'price_single')

    def test_unknown_plan_type_raises(self):
        for bad in ('gold', '', None):
            with self.assertRaises(ValueError):
                price_id_for(bad)

    @override_settings(STRIPE_PRICE_ID_SINGLE='')
    def test_unset_price_raises(self):
        with self.assertRaises(ValueError):
            price_id_for('single')


@override_settings(**PRICES)
class StartCheckoutTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory()
        UserProfileFactory(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)
        grant(self.org)
        self.client = Client()
        self.client.force_login(self.admin)

    def start(self, plan_type):
        with patch(CREATE, return_value=SESSION) as create:
            response = self.client.post(reverse('subscriptions:start_checkout'),
                                        {'plan_type': plan_type})
        return response, create

    def test_buying_a_round_is_bound_to_the_organization(self):
        response, create = self.start('single')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], SESSION.url)
        params = create.call_args.kwargs
        self.assertEqual(params['mode'], 'payment')
        self.assertEqual(params['client_reference_id'], str(self.org.pk))
        self.assertEqual(params['metadata'], {'plan_type': 'single', 'user_id': str(self.admin.pk)})
        self.assertEqual(params['line_items'][0]['price'], 'price_single')
        self.assertEqual(params['payment_method_types'], ['card'])

    def test_upgrading_starts_a_subscription_with_the_trial(self):
        _, create = self.start('saas')
        params = create.call_args.kwargs
        self.assertEqual(params['mode'], 'subscription')
        self.assertEqual(params['subscription_data'], {'trial_period_days': 14})
        self.assertEqual(params['client_reference_id'], str(self.org.pk))

    def test_subscription_is_refused_when_a_subscription_row_exists(self):
        subscribe(self.org, status='canceled')
        response, create = self.start('saas')
        create.assert_not_called()
        self.assertRedirects(response, reverse('settings'), fetch_redirect_response=False)

    def test_buying_a_round_is_still_allowed_with_a_canceled_subscription(self):
        subscribe(self.org, status='canceled')
        _, create = self.start('single')
        create.assert_called_once()

    def test_non_admins_cannot_start_checkout(self):
        member = UserFactory()
        UserProfileFactory(user=member, organization=self.org)
        self.client.force_login(member)
        _, create = self.start('single')
        create.assert_not_called()

    def test_unknown_plan_type_does_not_reach_stripe(self):
        for bad in ('gold', ''):
            response, create = self.start(bad)
            create.assert_not_called()
            self.assertRedirects(response, reverse('settings'), fetch_redirect_response=False)


@override_settings(**PRICES)
class PublicEndpointTests(TestCase):
    def post(self, client, body):
        with patch(CREATE, return_value=SESSION) as create:
            response = client.post('/api/stripe/create-checkout-session/',
                                   data=json.dumps(body), content_type='application/json')
        return response, create

    def test_returns_session_id_and_url_and_ignores_client_price(self):
        response, create = self.post(Client(), {'plan_type': 'single', 'price_id': 'price_evil'})
        self.assertEqual(response.json(), {'session_id': 'cs_1', 'url': SESSION.url})
        self.assertEqual(create.call_args.kwargs['line_items'][0]['price'], 'price_single')

    def test_never_binds_to_an_organization_even_when_signed_in(self):
        org = OrganizationFactory()
        admin = UserFactory()
        UserProfileFactory(user=admin, organization=org)
        assign_organization_admin(admin)
        client = Client()
        client.force_login(admin)
        _, create = self.post(client, {'plan_type': 'saas'})
        self.assertNotIn('client_reference_id', create.call_args.kwargs)

    def test_unknown_plan_type_is_a_400(self):
        response, create = self.post(Client(), {'plan_type': 'gold'})
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()
