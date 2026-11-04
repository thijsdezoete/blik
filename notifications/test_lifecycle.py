import uuid
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.factories import RevieweeFactory, UserProfileFactory
from accounts.permissions import assign_organization_admin
from core.factories import OrganizationFactory, UserFactory
from core.models import Organization
from notifications import lifecycle
from notifications.models import SentEmail
from questionnaires.factories import QuestionnaireFactory
from reports.models import Report
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.models import ReviewCycle
from subscriptions.testing import subscribe


def days_ago(days):
    return timezone.now() - timedelta(days=days)


class LifecycleTestCase(TestCase):
    def setUp(self):
        self.org = self.organization(created_days_ago=3)

    def organization(self, created_days_ago, **kwargs):
        """An organization with one admin and one member, signed up some days ago."""
        org = OrganizationFactory(**kwargs)
        Organization.objects.filter(pk=org.pk).update(created_at=days_ago(created_days_ago))
        admin = UserFactory(email=f'admin-{org.pk}@example.com')
        UserProfileFactory(user=admin, organization=org)
        assign_organization_admin(admin)
        UserProfileFactory(user=UserFactory(email=f'member-{org.pk}@example.com'), organization=org)
        org.refresh_from_db()
        return org

    def cycle(self, org, created_days_ago=3, **kwargs):
        cycle = ReviewCycleFactory(
            reviewee=RevieweeFactory(organization=org),
            questionnaire=QuestionnaireFactory(organization=org),
            **kwargs,
        )
        ReviewCycle.objects.filter(pk=cycle.pk).update(created_at=days_ago(created_days_ago))
        return cycle

    def closed_cycle(self, org, closed_days_ago):
        cycle = self.cycle(org, created_days_ago=closed_days_ago + 20, status='completed')
        ReviewCycle.objects.filter(pk=cycle.pk).update(updated_at=days_ago(closed_days_ago))
        return cycle

    def report(self, cycle):
        return Report.objects.create(cycle=cycle, report_data={}, access_token=uuid.uuid4())

    def recipients(self):
        return sorted(address for message in mail.outbox for address in message.to)


class NoCycleNudgeTests(LifecycleTestCase):
    def test_selects_organizations_that_signed_up_two_to_fourteen_days_ago_without_a_cycle(self):
        too_new = self.organization(created_days_ago=1)
        too_old = self.organization(created_days_ago=20)
        with_cycle = self.organization(created_days_ago=3)
        self.cycle(with_cycle)

        due = lifecycle.organizations_without_cycle()

        self.assertIn(self.org, due)
        self.assertNotIn(too_new, due)
        self.assertNotIn(too_old, due)
        self.assertNotIn(with_cycle, due)

    def test_skips_inactive_and_lapsed_organizations(self):
        inactive = self.organization(created_days_ago=3, is_active=False)
        lapsed = self.organization(created_days_ago=3)
        subscribe(lapsed, status='canceled')

        due = lifecycle.organizations_without_cycle()

        self.assertNotIn(inactive, due)
        self.assertNotIn(lapsed, due)

    def test_goes_to_the_admins_once(self):
        self.assertTrue(lifecycle.send_no_cycle_nudge(self.org))
        self.assertFalse(lifecycle.send_no_cycle_nudge(self.org))

        self.assertEqual(self.recipients(), [f'admin-{self.org.pk}@example.com'])
        self.assertNotIn(self.org, lifecycle.organizations_without_cycle())

    def test_an_organization_without_admins_is_tried_again_later(self):
        org = OrganizationFactory()
        Organization.objects.filter(pk=org.pk).update(created_at=days_ago(3))

        self.assertFalse(lifecycle.send_no_cycle_nudge(org))
        self.assertIn(org, lifecycle.organizations_without_cycle())


class NoReviewersNudgeTests(LifecycleTestCase):
    def test_selects_organizations_whose_first_cycle_reached_no_reviewer(self):
        cycle = self.cycle(self.org)
        ReviewerTokenFactory(cycle=cycle, category='self', completed_at=timezone.now())
        ReviewerTokenFactory(cycle=cycle, category='peer')  # an unused invite-link token

        self.assertIn(self.org, lifecycle.organizations_without_reviewers())

    def test_skips_organizations_that_invited_a_reviewer(self):
        for reached in ({'invitation_sent_at': timezone.now()}, {'claimed_at': timezone.now()}):
            org = self.organization(created_days_ago=5)
            ReviewerTokenFactory(cycle=self.cycle(org), category='peer', **reached)

            self.assertNotIn(org, lifecycle.organizations_without_reviewers())

    def test_skips_cycles_younger_than_two_days(self):
        self.cycle(self.org, created_days_ago=1)

        self.assertNotIn(self.org, lifecycle.organizations_without_reviewers())


class NextCycleReminderTests(LifecycleTestCase):
    def test_selects_the_last_cycle_closed_about_six_months_ago(self):
        self.closed_cycle(self.org, closed_days_ago=300)
        last = self.closed_cycle(self.org, closed_days_ago=190)

        self.assertEqual(lifecycle.organizations_due_next_cycle(), [(self.org, last)])

    def test_skipped_when_a_newer_cycle_exists(self):
        self.closed_cycle(self.org, closed_days_ago=190)
        self.cycle(self.org, created_days_ago=30, status='completed')

        self.assertEqual(lifecycle.organizations_due_next_cycle(), [])

    def test_skipped_while_a_cycle_is_open(self):
        self.closed_cycle(self.org, closed_days_ago=190)
        self.cycle(self.org, created_days_ago=250)

        self.assertEqual(lifecycle.organizations_due_next_cycle(), [])

    def test_skipped_when_the_last_close_is_recent(self):
        self.closed_cycle(self.org, closed_days_ago=100)

        self.assertEqual(lifecycle.organizations_due_next_cycle(), [])

    def test_counts_people_with_a_report_from_a_closed_cycle_once(self):
        first = self.closed_cycle(self.org, closed_days_ago=300)
        self.report(first)
        second = self.cycle(self.org, status='completed')
        second.reviewee = first.reviewee
        second.save()
        self.report(second)
        self.report(self.closed_cycle(self.org, closed_days_ago=190))
        self.report(self.cycle(self.org))  # an open cycle
        hidden = self.report(self.closed_cycle(self.org, closed_days_ago=190))
        hidden.available = False
        hidden.save()
        self.report(self.closed_cycle(self.organization(created_days_ago=3), closed_days_ago=190))

        self.assertEqual(lifecycle.people_with_baseline(self.org), 2)

    def test_goes_out_once_per_last_cycle(self):
        last = self.closed_cycle(self.org, closed_days_ago=190)

        self.assertTrue(lifecycle.send_next_cycle_reminder(self.org, last))

        self.assertEqual(lifecycle.organizations_due_next_cycle(), [])
        self.assertEqual(len(mail.outbox), 1)


class ReportFollowUpTests(LifecycleTestCase):
    def delivered(self, report, days):
        SentEmail.objects.create(kind=SentEmail.REPORT_READY, object_id=report.pk)
        SentEmail.objects.filter(kind=SentEmail.REPORT_READY, object_id=report.pk).update(sent_at=days_ago(days))

    def test_selects_reports_delivered_about_a_month_ago(self):
        due = self.report(self.cycle(self.org, status='completed'))
        recent = self.report(self.cycle(self.org, status='completed'))
        never_delivered = self.report(self.cycle(self.org, status='completed'))
        self.delivered(due, 31)
        self.delivered(recent, 10)

        selected = lifecycle.reports_due_follow_up()

        self.assertEqual(selected, [due])
        self.assertNotIn(never_delivered, selected)

    def test_skips_reports_with_an_expired_link(self):
        report = self.report(self.cycle(self.org, status='completed'))
        report.access_token_expires = days_ago(1)
        report.save()
        self.delivered(report, 31)

        self.assertEqual(lifecycle.reports_due_follow_up(), [])

    def test_goes_to_the_reviewee_once(self):
        report = self.report(self.cycle(self.org, status='completed'))
        self.delivered(report, 31)

        self.assertTrue(lifecycle.send_report_follow_up(report))
        self.assertFalse(lifecycle.send_report_follow_up(report))

        self.assertEqual(self.recipients(), [report.cycle.reviewee.email])
        self.assertEqual(lifecycle.reports_due_follow_up(), [])


class PerceptionGapTests(LifecycleTestCase):
    def report_with(self, perception_gaps, peer_count):
        self.org.min_responses_for_anonymity = 3
        self.org.save()
        report = self.report(self.cycle(self.org, status='completed'))
        report.report_data = {
            'insights': {
                'perception_gaps': perception_gaps,
                'overall_sentiment': {'score': 3.0, 'self_avg': 4.0},
            },
            'by_section': {'1': {'questions': {'10': {'by_category': {
                'self': {'count': 1}, 'peer': {'count': peer_count},
            }}}}},
        }
        return report

    def test_a_gap_the_report_shows(self):
        self.assertTrue(lifecycle.has_perception_gap(self.report_with([{'type': 'overconfidence'}], peer_count=3)))

    def test_no_gap_in_the_report(self):
        self.assertFalse(lifecycle.has_perception_gap(self.report_with([], peer_count=3)))

    def test_a_gap_below_the_anonymity_threshold_does_not_count(self):
        self.assertFalse(lifecycle.has_perception_gap(self.report_with([{'type': 'overconfidence'}], peer_count=2)))

    def test_empty_report_data(self):
        self.assertFalse(lifecycle.has_perception_gap(self.report(self.cycle(self.org, status='completed'))))


class FeedbackConversationGuideTests(LifecycleTestCase):
    def test_the_first_report_sends_the_guide_to_the_admins_once(self):
        first = self.report(self.cycle(self.org, status='completed'))
        second = self.report(self.cycle(self.org, status='completed'))

        self.assertTrue(lifecycle.report_delivered(first))
        self.assertFalse(lifecycle.report_delivered(first))
        self.assertFalse(lifecycle.report_delivered(second))

        self.assertEqual(self.recipients(), [f'admin-{self.org.pk}@example.com'])

    def test_a_later_report_sends_no_guide(self):
        self.report(self.cycle(self.org, status='completed'))
        later = self.report(self.cycle(self.org, status='completed'))

        self.assertFalse(lifecycle.report_delivered(later))
        self.assertEqual(mail.outbox, [])

    def test_records_the_delivery_for_the_follow_up(self):
        report = self.report(self.cycle(self.org, status='completed'))

        lifecycle.report_delivered(report)

        self.assertTrue(SentEmail.objects.filter(kind=SentEmail.REPORT_READY, object_id=report.pk).exists())


class CycleSummaryTests(LifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.org.min_responses_for_anonymity = 3
        self.org.save()
        self.subject = self.cycle(self.org)
        ReviewerTokenFactory(cycle=self.subject, category='self', completed_at=timezone.now())
        ReviewerTokenFactory(cycle=self.subject, category='peer')  # an unused invite-link token

    def reviewers(self, invited, responded):
        for i in range(invited):
            ReviewerTokenFactory(
                cycle=self.subject, category='peer', reviewer_email=f'r{i}@example.com',
                invitation_sent_at=timezone.now(), completed_at=timezone.now() if i < responded else None,
            )

    def test_counts_invited_reviewers_without_the_self_assessment_or_unused_links(self):
        self.reviewers(invited=5, responded=4)

        summary = lifecycle.cycle_summary(self.subject)

        self.assertEqual((summary['responded'], summary['invited'], summary['response_rate']), (4, 5, 80))
        self.assertTrue(summary['enough_responses'])

    def test_leaves_the_counts_out_below_the_anonymity_threshold(self):
        self.reviewers(invited=5, responded=2)

        summary = lifecycle.cycle_summary(self.subject)

        self.assertFalse(summary['enough_responses'])
        self.assertIsNone(summary['responded'])
        self.assertIsNone(summary['invited'])
        self.assertIsNone(summary['response_rate'])

    def test_counts_the_organizations_cycles(self):
        self.cycle(self.org)
        self.cycle(self.org, status='completed')
        self.cycle(self.organization(created_days_ago=3))

        summary = lifecycle.cycle_summary(self.subject)

        self.assertEqual((summary['completed_cycles'], summary['open_cycles']), (2, 1))

    def test_goes_to_the_admins_once(self):
        self.reviewers(invited=3, responded=3)

        self.assertTrue(lifecycle.send_cycle_summary(self.subject))
        self.assertFalse(lifecycle.send_cycle_summary(self.subject))

        self.assertEqual(self.recipients(), [f'admin-{self.org.pk}@example.com'])


class SendLifecycleEmailsCommandTests(LifecycleTestCase):
    def test_a_second_run_sends_nothing(self):
        call_command('send_lifecycle_emails', stdout=StringIO())
        sent = len(mail.outbox)
        call_command('send_lifecycle_emails', stdout=StringIO())

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_dry_run_sends_nothing(self):
        call_command('send_lifecycle_emails', '--dry-run', stdout=StringIO())

        self.assertEqual(mail.outbox, [])
        self.assertIn(self.org, lifecycle.organizations_without_cycle())
