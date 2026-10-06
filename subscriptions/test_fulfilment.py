from unittest.mock import patch

import stripe
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase

from accounts.factories import RevieweeFactory, UserProfileFactory
from accounts.models import UserProfile
from core.factories import OrganizationFactory, UserFactory
from core.models import Organization
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle
from subscriptions import fulfilment as fulfilment_module
from subscriptions.fulfilment import fulfil_checkout, resolve_checkout_account
from subscriptions.models import (
    CheckoutFulfilment, OneTimeLoginToken, Plan, RoundPurchase, Subscription,
)
from subscriptions.testing import (
    STRIPE_SUBSCRIPTION, checkout_session, grant, subscribe, subscription_session,
)
from subscriptions.utils import check_employee_limit, cycle_credits, entitlement

RETRIEVE = 'subscriptions.fulfilment.stripe.Subscription.retrieve'
CANCEL = 'subscriptions.fulfilment.stripe.Subscription.cancel'


def stripe_subscription(**overrides):
    return stripe.Subscription.construct_from({**STRIPE_SUBSCRIPTION, **overrides}, 'sk_test')


class FulfilmentTestCase(TestCase):
    def setUp(self):
        patcher = patch('core.email.send_email')
        self.send_email = patcher.start()
        self.addCleanup(patcher.stop)
        Plan.objects.create(name='EU SaaS', plan_type='saas', price_monthly=49, max_employees=50)

    def existing_account(self, email='buyer@example.com'):
        org = OrganizationFactory()
        user = UserFactory(username=email, email=email)
        UserProfileFactory(user=user, organization=org)
        return org, user


class ResolveAccountTests(FulfilmentTestCase):
    def test_unknown_email_creates_user_organization_and_profile(self):
        account = resolve_checkout_account(checkout_session())
        self.assertTrue(account.user_created)
        self.assertTrue(account.password)
        self.assertEqual(account.user.email, 'buyer@example.com')
        self.assertEqual(account.organization.name, 'Buyer Inc')
        self.assertEqual(account.user.profile.organization, account.organization)
        self.assertTrue(account.user.has_perm('accounts.can_manage_organization'))

    def test_missing_customer_name_falls_back_to_the_email(self):
        session = checkout_session(customer_details={'email': 'buyer@example.com', 'name': None})
        self.assertEqual(resolve_checkout_account(session).organization.name, 'buyer@example.com')

    def test_existing_account_buying_a_round_resolves_to_its_organization(self):
        org, user = self.existing_account()
        before = Organization.objects.count()
        account = resolve_checkout_account(checkout_session())
        self.assertEqual((account.organization, account.user), (org, user))
        self.assertFalse(account.user_created)
        self.assertIsNone(account.rejection)
        self.assertEqual(Organization.objects.count(), before)

    def test_email_matching_ignores_case(self):
        org, _ = self.existing_account('Buyer@Example.com')
        self.assertEqual(resolve_checkout_account(checkout_session()).organization, org)

    def test_existing_account_starting_a_subscription_anonymously_is_rejected(self):
        self.existing_account()
        before = Organization.objects.count()
        account = resolve_checkout_account(subscription_session())
        self.assertEqual(account.rejection, 'rejected_existing_account')
        self.assertEqual(Organization.objects.count(), before)

    def test_existing_user_without_profile_gets_an_organization_and_keeps_credentials(self):
        user = UserFactory(username='buyer@example.com', email='buyer@example.com')
        password_hash = user.password
        account = resolve_checkout_account(checkout_session())
        user.refresh_from_db()
        self.assertEqual(account.user, user)
        self.assertFalse(account.user_created)
        self.assertIsNone(account.password)
        self.assertEqual(user.password, password_hash)
        self.assertEqual(UserProfile.objects.get(user=user).organization, account.organization)
        self.assertTrue(User.objects.get(pk=user.pk).has_perm('accounts.can_manage_organization'))

    def test_in_app_session_resolves_to_the_referenced_organization(self):
        org, user = self.existing_account('admin@example.com')
        session = checkout_session(client_reference_id=str(org.pk),
                                   metadata={'plan_type': 'single', 'user_id': str(user.pk)})
        before = (Organization.objects.count(), User.objects.count())
        account = resolve_checkout_account(session)
        self.assertEqual((account.organization, account.user), (org, user))
        self.assertFalse(account.user_created)
        self.assertEqual((Organization.objects.count(), User.objects.count()), before)

    def test_in_app_subscription_for_a_subscribed_organization_is_rejected(self):
        org, user = self.existing_account('admin@example.com')
        subscribe(org, status='canceled')
        session = subscription_session(client_reference_id=str(org.pk),
                                       metadata={'plan_type': 'saas', 'user_id': str(user.pk)})
        self.assertEqual(resolve_checkout_account(session).rejection,
                         'rejected_duplicate_subscription')

    def username_only_match(self):
        org = OrganizationFactory()
        user = UserFactory(username='buyer@example.com', email='other@example.com')
        UserProfileFactory(user=user, organization=org)
        return org, user

    def test_existing_user_matched_by_username_is_reused(self):
        org, user = self.username_only_match()
        before = (User.objects.count(), Organization.objects.count())
        account = resolve_checkout_account(checkout_session())
        self.assertEqual((account.user, account.organization), (user, org))
        self.assertFalse(account.user_created)
        self.assertEqual((User.objects.count(), Organization.objects.count()), before)

    def test_reference_without_a_member_is_ignored(self):
        org, _ = self.existing_account('admin@example.com')
        session = checkout_session(client_reference_id=str(org.pk),
                                   metadata={'plan_type': 'single'})
        account = resolve_checkout_account(session)
        self.assertNotEqual(account.organization, org)
        self.assertTrue(account.user_created)

    def test_reference_with_a_member_of_another_organization_is_ignored(self):
        org, _ = self.existing_account('admin@example.com')
        _, outsider = self.existing_account('outsider@example.com')
        for n, user_id in enumerate((str(outsider.pk), 'abc', '999999')):
            session = checkout_session(
                client_reference_id=str(org.pk),
                customer_details={'email': f'new{n}@example.com', 'name': 'New'},
                metadata={'plan_type': 'single', 'user_id': user_id})
            account = resolve_checkout_account(session)
            self.assertNotEqual(account.organization, org)
            self.assertTrue(account.user_created)


class FulfilRoundTests(FulfilmentTestCase):
    def test_new_buyer_gets_ten_credits_and_a_token_bound_to_the_checkout(self):
        fulfilment = fulfil_checkout(checkout_session())
        self.assertEqual(fulfilment.outcome, 'fulfilled')
        self.assertTrue(fulfilment.user_created)
        self.assertEqual(cycle_credits(fulfilment.organization), 10)
        self.assertEqual(fulfilment.login_token.user, fulfilment.user)
        self.assertEqual(self.send_email.call_args.kwargs['recipient_list'], ['buyer@example.com'])

    def test_same_session_twice_grants_once(self):
        first = fulfil_checkout(checkout_session())
        second = fulfil_checkout(checkout_session())
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(RoundPurchase.objects.count(), 1)
        self.assertEqual(cycle_credits(first.organization), 10)
        self.assertEqual(self.send_email.call_count, 1)

    def test_unpaid_session_writes_nothing(self):
        self.assertIsNone(fulfil_checkout(checkout_session(payment_status='unpaid')))
        self.assertFalse(CheckoutFulfilment.objects.exists())
        self.assertFalse(User.objects.filter(email='buyer@example.com').exists())

    def test_session_from_elsewhere_writes_nothing(self):
        self.assertIsNone(fulfil_checkout(checkout_session(metadata={})))
        self.assertIsNone(fulfil_checkout(checkout_session(metadata=None)))
        self.assertFalse(CheckoutFulfilment.objects.exists())

    def test_second_purchase_by_email_adds_credits_and_issues_no_token(self):
        first = fulfil_checkout(checkout_session())
        second = fulfil_checkout(checkout_session(id='cs_2'))
        self.assertEqual(second.organization, first.organization)
        self.assertFalse(second.user_created)
        self.assertEqual(cycle_credits(first.organization), 20)
        self.assertEqual(OneTimeLoginToken.objects.count(), 1)
        self.assertFalse(OneTimeLoginToken.objects.filter(fulfilment=second).exists())

    def test_existing_user_without_profile_buys_a_round_without_a_token(self):
        user = UserFactory(username='buyer@example.com', email='buyer@example.com')
        fulfilment = fulfil_checkout(checkout_session())
        self.assertEqual(fulfilment.user, user)
        self.assertEqual(cycle_credits(fulfilment.organization), 10)
        self.assertFalse(OneTimeLoginToken.objects.exists())

    def test_failure_part_way_leaves_nothing_and_a_retry_succeeds(self):
        with patch('subscriptions.fulfilment.RoundPurchase.objects.create',
                   side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                fulfil_checkout(checkout_session())
        self.assertFalse(User.objects.filter(email='buyer@example.com').exists())
        self.assertFalse(Organization.objects.filter(email='buyer@example.com').exists())
        self.assertFalse(CheckoutFulfilment.objects.exists())
        self.assertEqual(self.send_email.call_count, 0)

        fulfilment = fulfil_checkout(checkout_session())
        self.assertEqual(cycle_credits(fulfilment.organization), 10)

    def test_welcome_email_failure_keeps_the_grant_and_is_not_repeated(self):
        self.send_email.side_effect = Exception('smtp down')
        fulfilment = fulfil_checkout(checkout_session())
        self.assertEqual(cycle_credits(fulfilment.organization), 10)
        fulfil_checkout(checkout_session())
        self.assertEqual(self.send_email.call_count, 1)
        self.assertEqual(cycle_credits(fulfilment.organization), 10)

    def test_a_user_creation_race_is_retried_once(self):
        real = fulfilment_module.resolve_checkout_account
        calls = []

        def lose_the_race_once(session):
            calls.append(session['id'])
            if len(calls) == 1:
                raise IntegrityError('duplicate key value violates unique constraint')
            return real(session)

        with patch('subscriptions.fulfilment.resolve_checkout_account',
                   side_effect=lose_the_race_once):
            fulfilment = fulfil_checkout(checkout_session())
        self.assertEqual(len(calls), 2)
        self.assertEqual(cycle_credits(fulfilment.organization), 10)

    def test_username_only_match_buys_a_round_without_a_token(self):
        org = OrganizationFactory()
        user = UserFactory(username='buyer@example.com', email='other@example.com')
        UserProfileFactory(user=user, organization=org)
        fulfilment = fulfil_checkout(checkout_session())
        self.assertEqual(fulfilment.outcome, 'fulfilled')
        self.assertEqual(cycle_credits(org), 10)
        self.assertFalse(OneTimeLoginToken.objects.exists())

    def test_canceled_subscriber_who_buys_a_round_can_work_again(self):
        org, _ = self.existing_account()
        subscribe(org, status='canceled')
        self.assertFalse(check_employee_limit(org)[0])
        fulfil_checkout(checkout_session())
        self.assertEqual(check_employee_limit(org), (True, None))
        ReviewCycle.objects.create(reviewee=RevieweeFactory(organization=org),
                                   questionnaire=QuestionnaireFactory(organization=org))
        self.assertEqual(cycle_credits(org), 9)


class FulfilSubscriptionTests(FulfilmentTestCase):
    def test_new_customer_gets_an_organization_a_subscription_and_a_token(self):
        with patch(RETRIEVE, return_value=stripe_subscription()):
            fulfilment = fulfil_checkout(subscription_session())
        subscription = Subscription.objects.get(stripe_subscription_id='sub_1')
        self.assertEqual(subscription.organization, fulfilment.organization)
        self.assertEqual(subscription.status, 'trialing')
        self.assertEqual(subscription.stripe_customer_id, 'cus_1')
        self.assertTrue(OneTimeLoginToken.objects.filter(fulfilment=fulfilment).exists())

    def test_anonymous_checkout_with_an_existing_email_changes_nothing_and_cancels(self):
        org, user = self.existing_account()
        original = subscribe(org)
        with patch(RETRIEVE, return_value=stripe_subscription()), patch(CANCEL) as cancel:
            fulfilment = fulfil_checkout(subscription_session())
        self.assertEqual(fulfilment.outcome, 'rejected_existing_account')
        cancel.assert_called_once_with('sub_1')
        original.refresh_from_db()
        self.assertEqual(original.stripe_subscription_id, f'sub_{org.pk}')
        self.assertEqual(original.stripe_customer_id, f'cus_{org.pk}')
        self.assertEqual(Subscription.objects.count(), 1)
        self.assertFalse(OneTimeLoginToken.objects.exists())
        self.assertEqual(self.send_email.call_args.kwargs['recipient_list'], [user.email])

    def test_rejection_is_not_cancelled_twice_when_already_canceled(self):
        self.existing_account()
        with patch(RETRIEVE, return_value=stripe_subscription(status='canceled')), \
                patch(CANCEL) as cancel:
            fulfil_checkout(subscription_session())
        cancel.assert_not_called()

    def test_a_failed_cancel_leaves_the_session_unprocessed(self):
        self.existing_account()
        with patch(RETRIEVE, return_value=stripe_subscription()), \
                patch(CANCEL, side_effect=RuntimeError('stripe down')):
            with self.assertRaises(RuntimeError):
                fulfil_checkout(subscription_session())
        self.assertFalse(CheckoutFulfilment.objects.exists())

    def test_in_app_upgrade_creates_the_subscription_and_keeps_the_credits(self):
        org, user = self.existing_account('admin@example.com')
        grant(org, 7)
        session = subscription_session(
            client_reference_id=str(org.pk),
            metadata={'plan_type': 'saas', 'user_id': str(user.pk)},
        )
        with patch(RETRIEVE, return_value=stripe_subscription()):
            fulfilment = fulfil_checkout(session)
        self.assertEqual(fulfilment.outcome, 'fulfilled')
        self.assertEqual(entitlement(org), 'subscription')
        self.assertEqual(RoundPurchase.objects.get(organization=org).cycles_remaining, 7)
        self.assertFalse(OneTimeLoginToken.objects.exists())

    def test_in_app_checkout_for_a_subscribed_organization_is_rejected_and_cancelled(self):
        org, user = self.existing_account('admin@example.com')
        original = subscribe(org)
        session = subscription_session(client_reference_id=str(org.pk),
                                       metadata={'plan_type': 'saas', 'user_id': str(user.pk)})
        with patch(RETRIEVE, return_value=stripe_subscription()), patch(CANCEL) as cancel:
            fulfilment = fulfil_checkout(session)
        self.assertEqual(fulfilment.outcome, 'rejected_duplicate_subscription')
        cancel.assert_called_once_with('sub_1')
        original.refresh_from_db()
        self.assertEqual(original.stripe_subscription_id, f'sub_{org.pk}')
        self.assertEqual(Subscription.objects.count(), 1)

    def test_reference_without_a_member_never_gives_the_organization_a_subscription(self):
        org, _ = self.existing_account('admin@example.com')
        grant(org, 3)
        session = subscription_session(client_reference_id=str(org.pk))
        with patch(RETRIEVE, return_value=stripe_subscription()):
            fulfil_checkout(session)
        self.assertFalse(Subscription.objects.filter(organization=org).exists())

    def test_missing_plan_row_raises_so_the_event_is_retried(self):
        Plan.objects.all().delete()
        with patch(RETRIEVE, return_value=stripe_subscription()):
            with self.assertRaises(Plan.DoesNotExist):
                fulfil_checkout(subscription_session())
        self.assertFalse(CheckoutFulfilment.objects.exists())
