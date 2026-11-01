from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

import stripe

from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.factories import RevieweeFactory, UserProfileFactory
from accounts.permissions import assign_organization_admin
from blik.context_processors import billing as billing_context_processor
from core.factories import OrganizationFactory, UserFactory
from subscriptions.billing import card_expires_before, live_details
from subscriptions.models import Plan, Subscription
from subscriptions.services import change_plan
from subscriptions.testing import grant, subscribe
from subscriptions.utils import can_see_billing, packs_for, payment_error_text, reviewees_over_limit

BILLING = dict(STRIPE_SECRET_KEY='sk_test_x', STRIPE_WEBHOOK_SECRET='whsec_x',
               STRIPE_PRICE_ID_SAAS='price_saas', STRIPE_PRICE_ID_ENTERPRISE='price_ent',
               STRIPE_PRICE_ID_SINGLE='price_single')


def admin_of(organization):
    user = UserFactory()
    UserProfileFactory(user=user, organization=organization)
    assign_organization_admin(user)
    return user


@override_settings(**BILLING)
class CanSeeBillingTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = admin_of(self.org)

    def test_admins_of_paying_organizations_see_it_in_any_state(self):
        grant(self.org, 0)
        self.assertTrue(can_see_billing(self.org, self.admin))
        subscribe(self.org, status='canceled')
        self.assertTrue(can_see_billing(self.org, self.admin))

    def test_members_without_admin_rights_do_not(self):
        grant(self.org)
        member = UserFactory()
        UserProfileFactory(user=member, organization=self.org)
        self.assertFalse(can_see_billing(self.org, member))

    def test_organizations_that_never_paid_do_not(self):
        self.assertFalse(can_see_billing(self.org, self.admin))

    @override_settings(STRIPE_SECRET_KEY='')
    def test_instances_without_billing_do_not(self):
        grant(self.org)
        self.assertFalse(can_see_billing(self.org, self.admin))


class PacksTests(SimpleTestCase):
    def test_reviews_round_up_to_whole_packs(self):
        self.assertEqual([packs_for(n) for n in (1, 10, 11, 40, 41)], [1, 1, 2, 4, 5])

    def test_at_least_one_pack(self):
        self.assertEqual(packs_for(0), 1)

    def test_a_huge_number_does_not_overflow(self):
        self.assertEqual(packs_for(10 ** 400), 10 ** 399)


class PaymentErrorTests(SimpleTestCase):
    def test_known_decline_codes_get_clear_text(self):
        self.assertEqual(payment_error_text({'code': 'card_declined', 'decline_code': 'insufficient_funds'}),
                         'The card was declined: not enough funds.')
        self.assertEqual(payment_error_text({'code': 'expired_card'}), 'The card has expired.')

    def test_unknown_codes_fall_back_to_stripes_message(self):
        self.assertEqual(payment_error_text({'code': 'odd_code', 'message': 'Stripe says no.'}), 'Stripe says no.')

    def test_no_error_is_none(self):
        self.assertIsNone(payment_error_text(None))


class CardExpiryTests(SimpleTestCase):
    def test_a_card_is_valid_through_the_last_day_of_its_month(self):
        card = {'exp_month': 2, 'exp_year': 2028}
        self.assertFalse(card_expires_before(card, datetime(2028, 2, 29, 12, tzinfo=dt_timezone.utc)))
        self.assertTrue(card_expires_before(card, datetime(2028, 3, 1, tzinfo=dt_timezone.utc)))


@override_settings(**BILLING)
class DowngradeGuardTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.small = Plan.objects.create(name='Small', plan_type='saas', price_monthly=49, max_employees=2)
        self.big = Plan.objects.create(name='Big', plan_type='enterprise', price_monthly=99, max_employees=50)
        subscription = subscribe(self.org)
        subscription.plan = self.big
        subscription.save()
        for _ in range(3):
            RevieweeFactory(organization=self.org)
        RevieweeFactory(organization=self.org, is_active=False)

    def test_counts_only_active_reviewees_over_the_plan_limit(self):
        self.assertEqual(reviewees_over_limit(self.org, self.small), 1)
        self.assertEqual(reviewees_over_limit(self.org, self.big), 0)

    def test_a_downgrade_over_the_limit_never_reaches_stripe(self):
        client = Client()
        client.force_login(admin_of(self.org))
        with patch('subscriptions.services.stripe') as stripe_api:
            response = client.post(reverse('billing_change_plan', args=['saas']))
        self.assertEqual(response.status_code, 200)
        stripe_api.Subscription.modify.assert_not_called()
        self.assertEqual(self.org.subscription.plan, self.big)


@override_settings(**BILLING)
class CheckoutCustomerTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        grant(self.org)
        self.client = Client()
        self.client.force_login(admin_of(self.org))

    def start(self, **data):
        with patch('subscriptions.views.stripe.checkout.Session.create',
                   return_value=MagicMock(url='https://checkout.stripe.test/')) as create:
            self.client.post(reverse('subscriptions:start_checkout'), {'plan_type': 'single', **data})
        return create.call_args.kwargs

    def test_a_known_customer_is_reused_so_invoices_stay_together(self):
        self.org.stripe_customer_id = 'cus_known'
        self.org.save()
        params = self.start()
        self.assertEqual(params['customer'], 'cus_known')
        self.assertNotIn('customer_email', params)
        self.assertNotIn('customer_creation', params)

    def test_a_subscriber_without_a_backfilled_customer_reuses_the_subscriptions_one(self):
        subscribe(self.org, status='canceled')
        params = self.start()
        self.assertEqual(params['customer'], f'cus_org{self.org.pk}')
        self.assertNotIn('customer_creation', params)

    def test_without_a_customer_stripe_makes_one(self):
        params = self.start()
        self.assertEqual(params['customer_creation'], 'always')
        self.assertNotIn('customer', params)

    def test_vat_is_collected_on_every_checkout(self):
        params = self.start()
        self.assertEqual(params['automatic_tax'], {'enabled': True})
        self.assertEqual(params['tax_id_collection'], {'enabled': True})

    def test_the_number_of_reviews_buys_whole_packs(self):
        self.assertEqual(self.start(reviews='40')['line_items'][0]['quantity'], 4)
        self.assertEqual(self.start(reviews='41')['line_items'][0]['quantity'], 5)

    def test_the_buyer_can_change_the_number_of_packs_at_checkout(self):
        self.assertTrue(self.start()['line_items'][0]['adjustable_quantity']['enabled'])


@override_settings(**BILLING)
class BannerTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = admin_of(self.org)

    def problem(self):
        request = RequestFactory().get('/')
        request.user, request.organization = self.admin, self.org
        return billing_context_processor(request).get('billing_problem')

    def test_a_failed_payment_is_not_shown_as_an_ended_subscription(self):
        subscribe(self.org, status='past_due')
        self.assertEqual(self.problem(), 'unpaid')

    def test_an_ended_subscription_is_shown_as_ended(self):
        subscribe(self.org, status='canceled')
        self.assertEqual(self.problem(), 'lapsed')

    def test_nothing_while_everything_is_paid(self):
        subscribe(self.org, status='active')
        self.assertIsNone(self.problem())


def stripe_object(data):
    """A real StripeObject, as stripe-python returns: indexing works, .get() does not."""
    return stripe.StripeObject.construct_from(data, 'sk_test_x')


@override_settings(**BILLING)
class FailedPaymentTests(TestCase):
    def test_the_error_comes_from_the_failed_invoice_not_the_newest_payment(self):
        org = OrganizationFactory()
        subscription = subscribe(org, status='past_due')
        stripe_sub = stripe_object({
            'default_payment_method': None,
            'latest_invoice': {'next_payment_attempt': None,
                               'payments': {'data': [{'payment': {'payment_intent': 'pi_invoice'}}]}},
        })
        intent = stripe_object({'last_payment_error': {'code': 'card_declined', 'decline_code': 'insufficient_funds'}})
        with patch('subscriptions.billing.stripe.Invoice.list', return_value=stripe_object({'data': []})), \
                patch('subscriptions.billing.stripe.Subscription.retrieve', return_value=stripe_sub), \
                patch('subscriptions.billing.stripe.PaymentIntent.retrieve', return_value=intent) as retrieve:
            details = live_details(org, subscription)
        retrieve.assert_called_once_with('pi_invoice')
        self.assertEqual(details['payment_error'], 'The card was declined: not enough funds.')


@override_settings(**BILLING)
class ChangePlanTests(TestCase):
    def test_a_stale_copy_does_not_undo_what_a_webhook_saved(self):
        org = OrganizationFactory()
        stale = subscribe(org, status='active')
        big = Plan.objects.create(name='Big', plan_type='enterprise', price_monthly=99, max_employees=50)
        Subscription.objects.filter(pk=stale.pk).update(status='past_due')
        with patch('subscriptions.services.stripe'):
            change_plan(stale, big)
        saved = Subscription.objects.get(pk=stale.pk)
        self.assertEqual((saved.plan, saved.status), (big, 'past_due'))
