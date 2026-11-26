from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Reviewee
from core.models import Organization
from questionnaires.models import Question, Questionnaire, QuestionSection
from reviews.models import ReviewCycle, ReviewerToken, Response

from .services import generate_report
from .summary import reviewee_summary

READERS = ('all', 'manager', 'own')


class RevieweeSummaryTests(TestCase):
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
            name='Maya Jansen', email='maya@acme.example', department='Product Engineering',
            organization=self.organization,
        )

    def review(self, ratings, days_ago, status='completed'):
        """A cycle with one completed token and answer per rating, and its report when it is completed."""
        cycle = ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire, status=status)
        ReviewCycle.objects.filter(pk=cycle.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        cycle.refresh_from_db()
        for category, rating in ratings:
            self.answer(cycle, category, rating)
        if status == 'completed':
            generate_report(cycle)
        return cycle

    def answer(self, cycle, category, rating):
        token = ReviewerToken.objects.create(cycle=cycle, category=category, completed_at=timezone.now())
        Response.objects.create(cycle=cycle, question=self.question, token=token, category=category,
                                answer_data={'value': rating})

    def test_latest_score_and_change_come_from_the_stored_report(self):
        everyone = [('self', 3), ('manager', 3), ('peer', 3), ('peer', 3), ('peer', 3)]
        first = self.review(everyone, days_ago=200)
        latest = self.review(everyone, days_ago=10)
        running = self.review([('self', 4)], days_ago=1, status='active')
        ReviewerToken.objects.create(cycle=running, category='peer')
        # Numbers that no calculation from the answers gives: only the stored report has them
        report = latest.report
        report.report_data['insights']['overall_sentiment']['score'] = 4.1
        report.report_data['comparison']['overall_trend'] = {'direction': 'up', 'change': 0.3}
        report.save()

        summary = reviewee_summary(self.reviewee, 'all')

        self.assertEqual((summary['latest_score'], summary['change']), (4.1, 0.3))
        self.assertEqual(summary['change_since'], first.created_at.date())
        self.assertEqual([review['cycle'] for review in summary['reviews']], [running, latest, first])
        self.assertEqual([(review['answered'], review['invited']) for review in summary['reviews']],
                         [(1, 2), (5, 5), (5, 5)])
        self.assertEqual([review['report'] for review in summary['reviews']], [None, latest.report, first.report])
        self.assertEqual([review['score'] for review in summary['reviews']], [None, 4.1, 3.0])

    def test_no_change_with_one_report(self):
        self.review([('self', 3), ('manager', 4), ('peer', 4), ('peer', 4), ('peer', 4)], days_ago=10)

        summary = reviewee_summary(self.reviewee, 'all')

        self.assertEqual(summary['latest_score'], 4.0)
        self.assertIsNone(summary['change'])
        self.assertIsNone(summary['change_since'])

    def test_gap_is_absent_under_the_anonymity_threshold(self):
        cycle = self.review([('self', 2), ('manager', 4), ('peer', 4)], days_ago=10)

        for reader in READERS:
            with self.subTest(reader=reader):
                self.assertIsNone(reviewee_summary(self.reviewee, reader)['gap'])

        self.answer(cycle, 'peer', 4)
        generate_report(cycle)
        self.assertEqual(reviewee_summary(self.reviewee, 'own')['gap'], -2.0)

    def test_the_reviewee_gets_the_hidden_groups_left_out(self):
        self.organization.hide_below_threshold_from_managers = False
        self.organization.save()
        # Two peers are below the threshold of 3
        self.review([('self', 2), ('manager', 3), ('peer', 5), ('peer', 5)], days_ago=10)

        admin = reviewee_summary(self.reviewee, 'all')['latest_score']
        manager = reviewee_summary(self.reviewee, 'manager')['latest_score']
        own = reviewee_summary(self.reviewee, 'own')['latest_score']

        # The manager gets the version of the report page: view_report shows it the admin view
        self.assertEqual(manager, admin)
        self.assertEqual(own, 3.0)
        self.assertNotEqual(own, admin)

    def test_the_reviewee_gets_no_change_when_the_previous_report_hid_a_group(self):
        self.organization.hide_below_threshold_from_managers = False
        self.organization.save()
        # Two peers are below the threshold of 3: the change would give their answers away
        self.review([('self', 2), ('manager', 3), ('peer', 5), ('peer', 5)], days_ago=200)
        self.review([('self', 3), ('manager', 4), ('peer', 4), ('peer', 4), ('peer', 4)], days_ago=10)

        self.assertIsNotNone(reviewee_summary(self.reviewee, 'all')['change'])
        own = reviewee_summary(self.reviewee, 'own')
        self.assertIsNone(own['change'])
        self.assertIsNone(own['change_since'])

    def test_unavailable_report_gives_no_numbers(self):
        cycle = self.review([('self', 3), ('manager', 4), ('peer', 4), ('peer', 4), ('peer', 4)], days_ago=10)
        cycle.report.available = False
        cycle.report.save()

        summary = reviewee_summary(self.reviewee, 'all')

        self.assertEqual(summary['reviews'][0]['report'], None)
        self.assertEqual(summary['reviews'][0]['score'], None)
        self.assertEqual([summary[key] for key in ('latest_score', 'change', 'change_since', 'gap')],
                         [None, None, None, None])
