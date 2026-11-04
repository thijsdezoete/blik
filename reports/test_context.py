from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Reviewee, UserProfile
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
