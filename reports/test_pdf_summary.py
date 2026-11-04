from django.test import TestCase

from accounts.models import Reviewee
from core.models import Organization
from questionnaires.models import Question, Questionnaire, QuestionSection
from reviews.models import ReviewCycle, ReviewerToken, Response

from .context import build_report_context
from .pdf_summary import executive_summary
from .services import generate_report


class ExecutiveSummaryTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='Acme', email='org@acme.example', min_responses_for_anonymity=1,
        )
        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=self.organization)
        reviewee = Reviewee.objects.create(name='Dana', email='dana@acme.example', organization=self.organization)
        self.cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=self.questionnaire)

    def add_section(self, title, ratings, mapping=None):
        """One rating question; ratings maps a category to its ratings. A peer average needs two of them."""
        section = QuestionSection.objects.create(
            questionnaire=self.questionnaire, title=title, order=self.questionnaire.sections.count(),
        )
        config = {'min': 1, 'max': 5}
        if mapping:
            config['dreyfus_mapping'] = mapping
        question = Question.objects.create(
            section=section, question_text=f'{title}?', question_type='rating', config=config,
        )
        for category, values in ratings.items():
            for rating in values:
                token = ReviewerToken.objects.create(cycle=self.cycle, category=category)
                Response.objects.create(
                    cycle=self.cycle, question=question, token=token, category=category,
                    answer_data={'value': rating},
                )

    def summary(self):
        report = generate_report(self.cycle)
        return executive_summary(build_report_context(report, is_admin_view=True))

    def test_summary_without_self_assessment(self):
        self.add_section('Craft', {'peer': [4, 4], 'manager': [5]}, {'skill': 1.0, 'agency': 1.0})

        summary = self.summary()

        self.assertIsNone(summary['self_gap'])
        self.assertIsNone(summary['sections_below_self_count'])
        self.assertEqual(summary['overall']['score'], 4.5)
        self.assertTrue(summary['overall']['rating'])
        self.assertIsNone(summary['overall']['trend'])
        self.assertIsNotNone(summary['skill'])
        self.assertIsNotNone(summary['agency'])
        self.assertTrue(summary['quadrant']['name'])
        self.assertEqual([s['area'] for s in summary['strengths']], ['Craft'])
        self.assertTrue(summary['next_steps'])

    def test_summary_with_self_assessment(self):
        self.add_section('Craft', {'self': [5], 'peer': [3, 3], 'manager': [3]})
        self.add_section('Teamwork', {'self': [2], 'peer': [4, 4]})

        summary = self.summary()

        self.assertEqual(summary['self_gap'], {'self_avg': 3.5, 'gap': 0.17})
        self.assertEqual(summary['sections_below_self_count'], 1)

    def test_summary_without_dreyfus_mapping(self):
        self.add_section('Craft', {'self': [3], 'peer': [4, 4]})

        summary = self.summary()

        self.assertIsNone(summary['skill'])
        self.assertIsNone(summary['agency'])
        self.assertIsNone(summary['quadrant'])
        self.assertEqual(summary['next_steps'], [])
        self.assertIsNotNone(summary['overall'])

    def test_summary_caps_list_lengths(self):
        for title in ['A', 'B', 'C', 'D']:
            self.add_section(title, {'peer': [5, 5]})
        for title in ['E', 'F', 'G']:
            self.add_section(title, {'peer': [1, 1]})

        summary = self.summary()

        self.assertEqual(len(summary['strengths']), 3)
        self.assertEqual(len(summary['growth']), 2)

    def test_summary_without_visible_others(self):
        self.organization.min_responses_for_anonymity = 3
        self.organization.save()
        self.add_section('Craft', {'self': [4], 'peer': [2, 2]})

        summary = self.summary()

        self.assertIsNone(summary['overall'])
        self.assertIsNone(summary['self_gap'])
        self.assertEqual(summary['strengths'], [])
        self.assertEqual(summary['growth'], [])
        self.assertIsNone(summary['sections_below_self_count'])

    def test_sections_below_self_skips_sections_without_visible_others(self):
        self.organization.min_responses_for_anonymity = 3
        self.organization.save()
        # Peers are hidden everywhere, so only the section with a manager score can be compared
        self.add_section('Craft', {'self': [5], 'peer': [2, 2], 'manager': [3]})
        self.add_section('Teamwork', {'self': [1], 'peer': [4, 4]})

        summary = self.summary()

        self.assertEqual(summary['sections_below_self_count'], 1)

