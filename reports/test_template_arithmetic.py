"""
Numbers the templates used to compute with `add:"-"`.

`add` cannot subtract: `6|add:"-"` renders an empty string, so the pending counts stayed
empty, the reminder button never showed, the percentile badge always read "Top 0%" and the
Likert summary never appeared.
"""
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory


class PendingCountTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.cycle = ReviewCycleFactory()
        admin = User.objects.create_user(username='admin', email='admin@example.com', password='pw')
        UserProfile.objects.create(user=admin, organization=self.cycle.reviewee.organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

    def test_cycle_detail_shows_the_pending_count_and_the_reminder_button(self):
        ReviewerTokenFactory(cycle=self.cycle, completed_at=timezone.now())
        ReviewerTokenFactory(cycle=self.cycle)
        pending = self.cycle.tokens.filter(completed_at__isnull=True).count()

        response = self.client.get(reverse('review_cycle_detail', args=[self.cycle.uuid]))

        self.assertContains(response, f'<div class="stat-number warning">{pending}</div>', html=True)
        self.assertContains(response, f'Send Reminders ({pending})')

    def test_invitations_page_shows_the_unsent_count(self):
        ReviewerTokenFactory(cycle=self.cycle, reviewer_email='a@example.com')
        ReviewerTokenFactory(cycle=self.cycle, reviewer_email='b@example.com')
        ReviewerTokenFactory(cycle=self.cycle, reviewer_email='c@example.com', invitation_sent_at=timezone.now())

        response = self.client.get(reverse('manage_invitations', args=[self.cycle.uuid]))

        self.assertContains(response, '2 pending invitations')


class ReportArithmeticTests(TestCase):
    def test_percentile_badge_shows_the_top_share(self):
        report = SimpleNamespace(report_data={
            'section_summary': {'Communication': {'peer': 4.5}},
            'peer_benchmarks': {'Communication': {
                'percentile': 85, 'show_percentile': True, 'current_score': 4.5, 'peer_median': 3.9,
            }},
        })

        # The report views always pass the cycle, the report data and its display data along with the report.
        cycle = SimpleNamespace(organization=SimpleNamespace(min_responses_for_anonymity=3))

        html = render_to_string('reports/_report_content.html', {
            'report': report, 'report_data': report.report_data, 'display_data': report.report_data,
            'cycle': cycle, 'is_admin_view': False,
        })

        self.assertIn('Top 15% in organization', html)

    def test_likert_summary_counts_agree_and_strongly_agree(self):
        question_data = {
            'question_text': 'Communicates clearly',
            'question_type': 'likert',
            'question_config': {'scale': ['Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree']},
            'category_order': ['peer'],
            'by_category': {'peer': {'count': 4, 'distribution': {'Strongly Agree': 2, 'Agree': 1, 'Neutral': 1}}},
        }

        html = render_to_string('reports/_question_response.html', {'question_data': question_data})

        self.assertIn('Strong consensus: 75% positive (3 of 4 respondents)', html)
