from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from reports.models import Report

from .factories import ReviewCycleFactory, ReviewerTokenFactory


class LastSubmissionTests(TestCase):
    def test_last_submission_closes_cycle_without_generating_report(self):
        cycle = ReviewCycleFactory(status='active')
        organization = cycle.reviewee.organization
        organization.auto_send_report_email = True
        organization.save()
        # Without a user and an organization, the setup middleware redirects every request
        UserProfile.objects.create(user=User.objects.create_user(username='admin'), organization=organization)
        token = ReviewerTokenFactory(cycle=cycle, reviewer_email='peer@example.org')

        response = self.client.post(reverse('reviews:submit_feedback', args=[token.token]))

        self.assertEqual(response.status_code, 200)
        cycle.refresh_from_db()
        self.assertEqual(cycle.status, 'completed')
        self.assertIsNone(cycle.report_finalized_at)
        self.assertFalse(Report.objects.filter(cycle=cycle).exists())
        self.assertNotIn([cycle.reviewee.email], [message.to for message in mail.outbox])
