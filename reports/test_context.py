from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Reviewee
from core.models import Organization
from questionnaires.models import Question, Questionnaire, QuestionSection
from reviews.models import ReviewCycle, ReviewerToken, Response

from .context import build_report_context
from .services import generate_report


class BuildReportContextTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='Acme', email='org@acme.example', min_responses_for_anonymity=3,
        )
        questionnaire = Questionnaire.objects.create(name='Skills', organization=self.organization)
        section = QuestionSection.objects.create(questionnaire=questionnaire, title='Growth')
        question = Question.objects.create(
            section=section, question_text='Solves problems', question_type='rating',
            config={'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1.0}},
        )
        reviewee = Reviewee.objects.create(name='Dana', email='dana@acme.example', organization=self.organization)
        self.cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=questionnaire)

        # Two peers are below the threshold of 3
        for category, rating in [('self', 2), ('manager', 3), ('peer', 4), ('peer', 5)]:
            token = ReviewerToken.objects.create(cycle=self.cycle, category=category)
            Response.objects.create(
                cycle=self.cycle, question=question, token=token, category=category,
                answer_data={'value': rating},
            )
        self.report = generate_report(self.cycle)

    def test_context_uses_org_threshold(self):
        context = build_report_context(self.report, is_admin_view=True)

        peer = context['report_data']['section_summary']['Growth']['peer']
        self.assertTrue(peer['insufficient'])
        self.assertNotIn('peer', context['report_data']['charts']['overall'])
        self.assertIs(context['display_data'], context['report_data'])

    def test_admin_and_reviewee_context_differ_only_in_flag(self):
        admin = build_report_context(self.report, is_admin_view=True)
        reviewee = build_report_context(self.report, is_admin_view=False)

        self.assertTrue(admin.pop('is_admin_view'))
        self.assertFalse(reviewee.pop('is_admin_view'))
        self.assertEqual(admin.keys(), reviewee.keys())
        self.assertEqual(admin['report_data'], reviewee['report_data'])
        self.assertEqual(admin['summary'], reviewee['summary'])

    def test_managers_see_groups_below_the_threshold_when_the_organization_allows_it(self):
        self.organization.hide_below_threshold_from_managers = False
        self.organization.save()

        admin = build_report_context(self.report, is_admin_view=True)
        reviewee = build_report_context(self.report, is_admin_view=False)

        self.assertEqual(admin['report_data']['section_summary']['Growth']['peer'], 4.5)
        self.assertTrue(reviewee['report_data']['section_summary']['Growth']['peer']['insufficient'])


class PreviousCycleTrendTests(TestCase):
    """Trends compare with the previous report's raw combined values, which include its hidden groups."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name='Acme', email='org@acme.example', min_responses_for_anonymity=3,
        )
        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=self.organization)
        section = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Growth')
        self.question = Question.objects.create(
            section=section, question_text='Solves problems', question_type='rating',
            config={'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1.0}},
        )
        self.reviewee = Reviewee.objects.create(
            name='Dana', email='dana@acme.example', organization=self.organization,
        )

    def _report(self, ratings, days_ago):
        cycle = ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)
        ReviewCycle.objects.filter(pk=cycle.pk).update(
            status='completed', created_at=timezone.now() - timedelta(days=days_ago),
        )
        cycle.refresh_from_db()
        for category, rating in ratings:
            token = ReviewerToken.objects.create(cycle=cycle, category=category)
            Response.objects.create(
                cycle=cycle, question=self.question, token=token, category=category,
                answer_data={'value': rating},
            )
        return generate_report(cycle)

    def test_previous_report_with_hidden_group_drops_trends(self):
        # Two peers are below the threshold of 3 in the previous cycle
        self._report([('self', 2), ('manager', 3), ('peer', 1), ('peer', 2)], days_ago=60)
        current = self._report(
            [('self', 2), ('manager', 3), ('peer', 4), ('peer', 5), ('peer', 5)], days_ago=1,
        )
        self.assertIn('overall_trend', current.report_data['comparison'])

        comparison = build_report_context(current, is_admin_view=True)['report_data']['comparison']

        self.assertTrue(comparison['has_previous'])
        self.assertNotIn('overall_trend', comparison)
        self.assertNotIn('section_trends', comparison)

    def test_both_reports_clean_keep_trends(self):
        self._report([('self', 2), ('manager', 3), ('peer', 1), ('peer', 2), ('peer', 2)], days_ago=60)
        current = self._report(
            [('self', 2), ('manager', 3), ('peer', 4), ('peer', 5), ('peer', 5)], days_ago=1,
        )

        comparison = build_report_context(current, is_admin_view=True)['report_data']['comparison']

        stored = current.report_data['comparison']
        self.assertEqual(comparison['overall_trend']['change'], stored['overall_trend']['change'])
        self.assertEqual(
            comparison['section_trends']['Growth']['change'], stored['section_trends']['Growth']['change'],
        )
