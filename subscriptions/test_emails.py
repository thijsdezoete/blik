"""Which subscription changes send which email, and that each one goes out once."""
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.factories import RevieweeFactory, UserProfileFactory
from accounts.permissions import assign_organization_admin
from core.factories import OrganizationFactory, UserFactory
from subscriptions import services, views
from reports.models import Report
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from subscriptions.emails import (
    _usage, billing_recipients, change_email, next_step, next_trial_reminder, send_cancellation_email,
    send_trial_reminders, snapshot,
    trial_ending_subject, trial_ending_template,
)
from subscriptions.fulfilment import fulfil_checkout
from subscriptions.models import Plan, Subscription
from subscriptions.utils import billing_enabled
from subscriptions.testing import STRIPE_SUBSCRIPTION, subscribe, subscription_session

import stripe

# A working SaaS setup. Billing emails are only sent with one, so tests must not depend on the local .env.
BILLING = dict(STRIPE_SECRET_KEY='sk_test_x', STRIPE_WEBHOOK_SECRET='whsec_x', STRIPE_PRICE_ID_SAAS='price_saas')
NO_BILLING = dict(STRIPE_SECRET_KEY='', STRIPE_WEBHOOK_SECRET='', STRIPE_PRICE_ID_SAAS='', STRIPE_PRICE_ID_ENTERPRISE='')


@override_settings(**BILLING)
class SubscriptionEmailTestCase(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory(email='admin@example.com')
        UserProfileFactory(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)
        self.subscription = subscribe(self.org, status='trialing')

    def stripe_object(self, **overrides):
        """The subscription as a Stripe webhook delivers it, in its current local state plus overrides."""
        end = int(self.subscription.current_period_end.timestamp())
        values = {
            'id': self.subscription.stripe_subscription_id,
            'status': self.subscription.status,
            'cancel_at_period_end': self.subscription.cancel_at_period_end,
            'items': {'data': [{'current_period_start': end - 86400, 'current_period_end': end}]},
        }
        values.update(overrides)
        return values


class BillingRecipientsTests(SubscriptionEmailTestCase):
    def test_only_active_administrators(self):
        member = UserFactory(email='member@example.com')
        UserProfileFactory(user=member, organization=self.org)
        gone = UserFactory(email='gone@example.com', is_active=False)
        UserProfileFactory(user=gone, organization=self.org)
        assign_organization_admin(gone)

        self.assertEqual([email for _, email in billing_recipients(self.org)], ['admin@example.com'])

    def test_organization_email_when_there_is_no_administrator(self):
        org = OrganizationFactory(email='billing@example.com')
        self.assertEqual(billing_recipients(org), [(None, 'billing@example.com')])


class BillingEnabledTests(TestCase):
    def test_needs_a_secret_key_a_webhook_secret_and_a_subscription_price(self):
        with override_settings(**BILLING):
            self.assertTrue(billing_enabled())
        for missing in ('STRIPE_WEBHOOK_SECRET', 'STRIPE_PRICE_ID_SAAS'):
            with override_settings(**{**NO_BILLING, **BILLING, missing: ''}):
                self.assertFalse(billing_enabled(), missing)

    def test_a_placeholder_secret_key_does_not_count(self):
        with override_settings(**{**BILLING, 'STRIPE_SECRET_KEY': 'changeme'}):
            self.assertFalse(billing_enabled())


@override_settings(**NO_BILLING)
class WithoutBillingTests(SubscriptionEmailTestCase):
    def test_no_trial_reminder_and_nothing_recorded(self):
        self.subscription.trial_end = timezone.now() + timedelta(days=2)
        self.subscription.save()

        self.assertEqual(send_trial_reminders()['sent'], 0)
        self.assertEqual(mail.outbox, [])
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.trial_reminder_3_days_sent_at)

    def test_no_cancellation_email(self):
        self.assertEqual(send_cancellation_email(self.subscription), 0)
        self.assertEqual(mail.outbox, [])


class TrialReminderTests(SubscriptionEmailTestCase):
    def ends_in(self, delta, **fields):
        self.subscription.trial_end = self.now + delta
        for name, value in fields.items():
            setattr(self.subscription, name, value)
        self.subscription.save()

    def setUp(self):
        super().setUp()
        self.now = timezone.now()

    def test_three_day_reminder_goes_out_once(self):
        self.ends_in(timedelta(days=2, hours=20))

        self.assertEqual(send_trial_reminders(now=self.now)['sent'], 1)
        self.assertEqual(send_trial_reminders(now=self.now + timedelta(hours=1))['sent'], 0)
        self.assertEqual(len(mail.outbox), 1)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.trial_reminder_3_days_sent_at, self.now)
        self.assertIsNone(self.subscription.trial_reminder_1_day_sent_at)

    def test_one_day_reminder_follows_the_three_day_one(self):
        self.ends_in(timedelta(hours=20), trial_reminder_3_days_sent_at=self.now - timedelta(days=2))

        self.assertEqual(send_trial_reminders(now=self.now)['sent'], 1)
        self.assertEqual(send_trial_reminders(now=self.now)['sent'], 0)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.trial_reminder_1_day_sent_at, self.now)

    def test_a_missed_three_day_reminder_is_replaced_by_the_one_day_one(self):
        self.ends_in(timedelta(hours=20))

        send_trial_reminders(now=self.now)
        self.subscription.refresh_from_db()
        self.assertIsNotNone(self.subscription.trial_reminder_1_day_sent_at)
        self.assertIsNone(self.subscription.trial_reminder_3_days_sent_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_no_reminder_more_than_three_days_ahead_or_after_the_end(self):
        self.ends_in(timedelta(days=3, hours=1))
        self.assertEqual(send_trial_reminders(now=self.now)['eligible'], 0)

        self.ends_in(-timedelta(hours=1))
        self.assertEqual(send_trial_reminders(now=self.now)['eligible'], 0)

    def test_no_reminder_when_the_trial_is_canceled_or_over(self):
        self.ends_in(timedelta(days=2), cancel_at_period_end=True)
        self.assertEqual(send_trial_reminders(now=self.now)['eligible'], 0)

        self.ends_in(timedelta(days=2), cancel_at_period_end=False, status='active')
        self.assertEqual(send_trial_reminders(now=self.now)['eligible'], 0)

    def test_dry_run_sends_and_records_nothing(self):
        self.ends_in(timedelta(days=2))

        self.assertEqual(send_trial_reminders(dry_run=True, now=self.now)['eligible'], 1)
        self.assertEqual(mail.outbox, [])
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.trial_reminder_3_days_sent_at)

    def test_a_failed_send_is_not_recorded(self):
        self.ends_in(timedelta(days=2))

        with patch('notifications.log.send_email', side_effect=OSError('smtp down')):
            stats = send_trial_reminders(now=self.now)

        self.assertEqual((stats['sent'], len(stats['errors'])), (0, 1))
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.trial_reminder_3_days_sent_at)


class NextTrialReminderTests(SubscriptionEmailTestCase):
    ends_in = TrialReminderTests.ends_in

    def setUp(self):
        super().setUp()
        self.now = timezone.now()

    def test_three_days_before_the_end_then_one_day_before(self):
        self.ends_in(timedelta(days=5))
        self.assertEqual(next_trial_reminder(self.subscription, self.now), self.now + timedelta(days=2))

        self.ends_in(timedelta(days=5), trial_reminder_3_days_sent_at=self.now)
        self.assertEqual(next_trial_reminder(self.subscription, self.now), self.now + timedelta(days=4))

    def test_the_one_day_reminder_replaces_an_unsent_three_day_one(self):
        self.ends_in(timedelta(hours=20))
        self.assertEqual(next_trial_reminder(self.subscription, self.now), self.now - timedelta(hours=4))

    def test_none_when_both_went_out_or_nothing_will_be_charged(self):
        self.ends_in(timedelta(hours=20), trial_reminder_1_day_sent_at=self.now)
        self.assertIsNone(next_trial_reminder(self.subscription, self.now))

        self.ends_in(timedelta(days=5), trial_reminder_1_day_sent_at=None, cancel_at_period_end=True)
        self.assertIsNone(next_trial_reminder(self.subscription, self.now))

    def test_the_reminder_goes_out_on_the_first_run_after_the_due_time(self):
        self.ends_in(timedelta(days=5))
        due = next_trial_reminder(self.subscription, self.now)

        self.assertEqual(send_trial_reminders(now=due - timedelta(minutes=1))['sent'], 0)
        self.assertEqual(send_trial_reminders(now=due + timedelta(minutes=1))['sent'], 1)


class UsageTests(SubscriptionEmailTestCase):
    def test_counts_open_work_and_people_with_feedback(self):
        anna, ben = RevieweeFactory(organization=self.org), RevieweeFactory(organization=self.org)
        open_cycle = ReviewCycleFactory(reviewee=anna)
        reported = ReviewCycleFactory(reviewee=anna)
        Report.objects.create(cycle=reported, report_data={})
        done = ReviewCycleFactory(reviewee=ben, status='completed')
        ReviewCycleFactory()  # Another organization
        for cycle in (open_cycle, open_cycle, done):
            ReviewerTokenFactory(cycle=cycle, completed_at=timezone.now())
        ReviewerTokenFactory(cycle=open_cycle)  # Not completed

        usage = _usage(self.org)

        self.assertEqual(usage['cycle_count'], 3)
        self.assertEqual(usage['open_cycle_count'], 2)
        self.assertEqual(usage['pending_report_count'], 1)
        self.assertEqual(usage['completed_review_count'], 3)
        self.assertEqual(usage['reviewed_people_count'], 2)


class TrialEndingVariantTests(TestCase):
    def usage(self, cycles=2, open_cycles=1, reports=1, reviews=41):
        return {'cycle_count': cycles, 'open_cycle_count': open_cycles, 'pending_report_count': reports,
                'completed_review_count': reviews, 'site_name': 'Blik', 'trial_end_date': '2 November 2026'}

    def test_template(self):
        self.assertEqual(trial_ending_template(3, self.usage()), 'trial_ending')
        self.assertEqual(trial_ending_template(1, self.usage()), 'trial_ending_last')
        self.assertEqual(trial_ending_template(3, self.usage(cycles=0)), 'trial_ending_empty')
        self.assertEqual(trial_ending_template(1, self.usage(cycles=0)), 'trial_ending_empty')

    def test_subject_carries_the_numbers(self):
        subject = trial_ending_subject(3, self.usage(reviews=41, reports=2))
        self.assertIn('41', subject)
        self.assertIn('2', subject)

    def test_one_day_subject_differs(self):
        for usage in (self.usage(), self.usage(cycles=0), self.usage(open_cycles=0, reports=0)):
            self.assertNotEqual(trial_ending_subject(1, usage), trial_ending_subject(3, usage))

    def test_subject_without_numbers_names_no_zeros(self):
        for usage in (self.usage(open_cycles=0, reports=0, reviews=0), self.usage(cycles=0, open_cycles=0,
                                                                                  reports=0, reviews=0)):
            for days in (1, 3):
                self.assertNotIn('0', trial_ending_subject(days, usage).replace('2026', ''))


class NextStepTests(TestCase):
    def test_next_step_follows_the_organization_state(self):
        self.assertEqual(next_step({'cycle_count': 0, 'open_cycle_count': 0}), 'first_cycle')
        self.assertEqual(next_step({'cycle_count': 3, 'open_cycle_count': 1}), 'follow_up')
        self.assertEqual(next_step({'cycle_count': 3, 'open_cycle_count': 0}), 'next_cycle')


class ChangeEmailTests(SubscriptionEmailTestCase):
    def change(self, **fields):
        before = snapshot(self.subscription)
        for name, value in fields.items():
            setattr(self.subscription, name, value)
        return change_email(before, self.subscription)

    def test_failed_first_payment_after_the_trial_pauses(self):
        self.assertEqual(self.change(status='past_due'), 'trial_ended')

    def test_trial_that_converts_is_active(self):
        self.assertEqual(self.change(status='active'), 'active')

    def test_scheduled_cancellation(self):
        self.assertEqual(self.change(cancel_at_period_end=True), 'canceled')

    def test_undone_cancellation(self):
        self.subscription.cancel_at_period_end = True
        self.assertEqual(self.change(cancel_at_period_end=False), 'resumed')

    def test_plan_change(self):
        self.subscription.status = 'active'
        enterprise = Plan.objects.create(name='Enterprise', plan_type='enterprise', price_monthly=99, max_employees=500)
        self.assertEqual(self.change(plan=enterprise), 'plan_changed')

    def test_canceled_trial_that_ends_needs_no_email(self):
        self.subscription.cancel_at_period_end = True
        self.assertIsNone(self.change(status='canceled'))

    def test_renewal_needs_no_email(self):
        self.subscription.status = 'active'
        self.assertIsNone(self.change(current_period_end=timezone.now() + timedelta(days=30)))

    def test_failed_renewal_is_left_to_stripe(self):
        self.subscription.status = 'active'
        self.assertIsNone(self.change(status='past_due'))


@override_settings(STRIPE_PRICE_ID_SAAS='price_saas', STRIPE_PRICE_ID_ENTERPRISE='price_ent')
class WebhookEmailTests(SubscriptionEmailTestCase):
    def test_cancellation_is_confirmed_once(self):
        event = self.stripe_object(cancel_at_period_end=True)

        views.handle_subscription_updated(event)
        views.handle_subscription_updated(event)  # Stripe retries

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['admin@example.com'])

    def test_trial_ending_without_payment_sends_the_paused_email(self):
        with patch('subscriptions.emails.send_trial_ended_email') as send:
            views.handle_subscription_updated(self.stripe_object(status='past_due'))

        send.assert_called_once_with(self.subscription)

    def test_paused_email_goes_out_once_whichever_event_comes_first(self):
        with patch('subscriptions.emails.send_trial_ended_email') as send:
            views.handle_payment_failed({'customer': self.subscription.stripe_customer_id})
            views.handle_subscription_updated(self.stripe_object(status='past_due'))

        send.assert_called_once()

    def test_plan_change_updates_the_plan_and_confirms_it(self):
        self.subscription.status = 'active'
        self.subscription.save()
        enterprise = Plan.objects.create(name='Enterprise', plan_type='enterprise', price_monthly=99, max_employees=500)
        event = self.stripe_object()
        event['items']['data'][0]['price'] = {'id': 'price_ent'}

        views.handle_subscription_updated(event)

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, enterprise)
        self.assertEqual(len(mail.outbox), 1)

    def test_unknown_price_keeps_the_plan(self):
        plan = self.subscription.plan
        event = self.stripe_object()
        event['items']['data'][0]['price'] = {'id': 'price_other'}

        views.handle_subscription_updated(event)

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, plan)
        self.assertEqual(mail.outbox, [])

    def test_immediate_cancellation_is_confirmed_once(self):
        event = self.stripe_object(status='canceled', cancellation_details={'reason': 'cancellation_requested'})

        views.handle_subscription_deleted(event)
        views.handle_subscription_deleted(event)

        self.assertEqual(len(mail.outbox), 1)

    def test_end_of_a_scheduled_cancellation_sends_nothing_more(self):
        self.subscription.cancel_at_period_end = True
        self.subscription.save()

        views.handle_subscription_deleted(
            self.stripe_object(status='canceled', cancellation_details={'reason': 'cancellation_requested'}))

        self.assertEqual(mail.outbox, [])

    def test_end_after_failed_payments_is_left_to_stripe(self):
        views.handle_subscription_deleted(
            self.stripe_object(status='canceled', cancellation_details={'reason': 'payment_failed'}))

        self.assertEqual(mail.outbox, [])
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, 'canceled')

    def test_a_failing_email_does_not_fail_the_webhook(self):
        with patch('notifications.log.send_email', side_effect=OSError('smtp down')):
            views.handle_subscription_updated(self.stripe_object(cancel_at_period_end=True))

        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.cancel_at_period_end)


class InAppCancellationTests(SubscriptionEmailTestCase):
    """Cancel and reactivate in Settings change the local state first, so the webhook sees no change."""

    @patch('subscriptions.services.stripe.Subscription.modify')
    def test_cancel_in_settings_is_confirmed_once(self, _):
        services.cancel_subscription(self.subscription)
        views.handle_subscription_updated(self.stripe_object())

        self.assertEqual(len(mail.outbox), 1)

    @patch('subscriptions.services.stripe.Subscription.modify')
    def test_reactivate_in_settings_is_confirmed_once(self, _):
        self.subscription.cancel_at_period_end = True
        self.subscription.save()

        services.reactivate_subscription(self.subscription)
        views.handle_subscription_updated(self.stripe_object())

        self.assertEqual(len(mail.outbox), 1)


@override_settings(**BILLING)
class CheckoutConfirmationTests(TestCase):
    def setUp(self):
        Plan.objects.create(name='EU SaaS', plan_type='saas', price_monthly=49, max_employees=50)
        self.org = OrganizationFactory()
        self.admin = UserFactory(email='admin@example.com')
        UserProfileFactory(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

    def test_existing_organization_starting_a_subscription_gets_the_trial_confirmation(self):
        session = subscription_session(
            client_reference_id=str(self.org.pk),
            metadata={'plan_type': 'saas', 'user_id': str(self.admin.pk)},
        )
        stripe_subscription = stripe.Subscription.construct_from(STRIPE_SUBSCRIPTION, 'sk_test')

        with patch('subscriptions.fulfilment.stripe.Subscription.retrieve', return_value=stripe_subscription):
            fulfil_checkout(session)
            fulfil_checkout(session)  # The success page after the webhook

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['admin@example.com'])
        self.assertTrue(Subscription.objects.filter(organization=self.org).exists())
