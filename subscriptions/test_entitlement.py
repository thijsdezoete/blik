from django.contrib.admin.sites import site
from django.test import TestCase

from accounts.factories import RevieweeFactory
from core.factories import OrganizationFactory, UserFactory
from subscriptions.models import RoundPurchase
from subscriptions.testing import grant, subscribe
from subscriptions.utils import (
    NoCycleCredits, billing_context, check_employee_limit, consume_cycle_credits,
    cycle_credits, entitlement, get_subscription_status, is_hosted_customer,
    purchased_credits,
)


class EntitlementTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()

    def test_no_subscription_and_no_purchases_is_self_hosted(self):
        self.assertEqual(entitlement(self.org), 'self_hosted')

    def test_active_and_trialing_subscriptions_are_subscription(self):
        sub = subscribe(self.org, status='active')
        self.assertEqual(entitlement(self.org), 'subscription')
        sub.status = 'trialing'
        sub.save()
        self.assertEqual(entitlement(self.org), 'subscription')

    def test_inactive_subscription_without_purchases_is_lapsed(self):
        for status in ('canceled', 'past_due', 'unpaid'):
            org = OrganizationFactory()
            subscribe(org, status=status)
            self.assertEqual(entitlement(org), 'lapsed', status)

    def test_purchases_without_subscription_is_credits(self):
        grant(self.org)
        self.assertEqual(entitlement(self.org), 'credits')

    def test_inactive_subscription_with_purchases_is_credits(self):
        for status in ('canceled', 'past_due'):
            org = OrganizationFactory()
            subscribe(org, status=status)
            grant(org, 0)
            self.assertEqual(entitlement(org), 'credits', status)

    def test_active_subscription_wins_over_purchases(self):
        subscribe(self.org)
        grant(self.org)
        self.assertEqual(entitlement(self.org), 'subscription')


class CreditTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()

    def test_cycle_credits_sums_purchases_in_credits_mode(self):
        grant(self.org, 3)
        grant(self.org, 10)
        self.assertEqual(cycle_credits(self.org), 13)

    def test_cycle_credits_is_none_outside_credits_mode(self):
        self.assertIsNone(cycle_credits(self.org))
        subscribe(self.org)
        grant(self.org, 5)
        self.assertIsNone(cycle_credits(self.org))
        self.assertEqual(purchased_credits(self.org), 5)

    def test_consume_takes_from_the_oldest_purchase_first(self):
        old = grant(self.org, 1)
        new = grant(self.org, 10)
        consume_cycle_credits(self.org, 3)
        old.refresh_from_db()
        new.refresh_from_db()
        self.assertEqual((old.cycles_remaining, new.cycles_remaining), (0, 8))

    def test_consume_raises_at_zero(self):
        grant(self.org, 0)
        with self.assertRaises(NoCycleCredits) as raised:
            consume_cycle_credits(self.org)
        self.assertEqual((raised.exception.needed, raised.exception.available), (1, 0))

    def test_consume_more_than_the_balance_takes_nothing(self):
        grant(self.org, 2)
        with self.assertRaises(NoCycleCredits):
            consume_cycle_credits(self.org, 3)
        self.assertEqual(cycle_credits(self.org), 2)

    def test_consume_is_a_no_op_outside_credits_mode(self):
        consume_cycle_credits(self.org)            # self_hosted
        lapsed = OrganizationFactory()
        subscribe(lapsed, status='canceled')
        consume_cycle_credits(lapsed)              # lapsed
        subscribe(self.org)
        grant(self.org, 4)
        consume_cycle_credits(self.org)            # subscription
        self.assertEqual(purchased_credits(self.org), 4)


class RevieweeGateTests(TestCase):
    def test_active_subscription_enforces_the_plan_cap(self):
        org = OrganizationFactory()
        subscribe(org, max_employees=1)
        self.assertEqual(check_employee_limit(org), (True, None))
        RevieweeFactory(organization=org)
        allowed, message = check_employee_limit(org)
        self.assertFalse(allowed)
        self.assertTrue(message)

    def test_canceled_subscription_without_purchases_is_blocked(self):
        org = OrganizationFactory()
        subscribe(org, status='canceled')
        self.assertFalse(check_employee_limit(org)[0])

    def test_canceled_subscription_with_purchases_is_allowed_even_at_zero(self):
        org = OrganizationFactory()
        subscribe(org, status='canceled')
        grant(org, 0)
        self.assertEqual(check_employee_limit(org), (True, None))

    def test_self_hosted_and_missing_organization_are_allowed(self):
        self.assertEqual(check_employee_limit(OrganizationFactory()), (True, None))
        self.assertEqual(check_employee_limit(None), (True, None))


class HostedAndStatusTests(TestCase):
    def test_is_hosted_customer(self):
        self.assertFalse(is_hosted_customer(OrganizationFactory()))
        subscribed = OrganizationFactory()
        subscribe(subscribed, status='canceled')
        self.assertTrue(is_hosted_customer(subscribed))
        bought = OrganizationFactory()
        grant(bought, 0)
        self.assertTrue(is_hosted_customer(bought))

    def test_status_reports_mode_and_credits(self):
        org = OrganizationFactory()
        grant(org, 7)
        status = get_subscription_status(org)
        self.assertEqual((status['mode'], status['cycle_credits']), ('credits', 7))
        self.assertFalse(status['has_subscription'])

    def test_status_for_canceled_subscriber_with_credits_hides_the_plan(self):
        org = OrganizationFactory()
        subscribe(org, status='canceled')
        grant(org, 2)
        self.assertFalse(get_subscription_status(org)['has_subscription'])

    def test_billing_context_offers_a_subscription_only_without_a_subscription_row(self):
        user = UserFactory()
        single = OrganizationFactory()
        grant(single)
        self.assertTrue(billing_context(single, user)['can_start_subscription'])
        canceled = OrganizationFactory()
        subscribe(canceled, status='canceled')
        grant(canceled)
        self.assertFalse(billing_context(canceled, user)['can_start_subscription'])
        self.assertFalse(billing_context(OrganizationFactory(), user)['can_start_subscription'])

    def test_round_purchases_cannot_be_deleted_in_admin(self):
        self.assertFalse(site._registry[RoundPurchase].has_delete_permission(request=None))
