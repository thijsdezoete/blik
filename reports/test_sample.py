from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.factories import UserProfileFactory
from core.models import Organization
from questionnaires.models import Question, Questionnaire, QuestionSection
from reports.models import Report
from reports.sample import SAMPLE_QUESTIONNAIRE, build_sample_pdf


class SampleReportTests(TestCase):
    def setUp(self):
        cache.clear()
        UserProfileFactory()  # the setup middleware redirects everything until one profile exists
        questionnaire = Questionnaire.objects.create(name=SAMPLE_QUESTIONNAIRE, organization=None)
        section = QuestionSection.objects.create(questionnaire=questionnaire, title='Leading', order=0)
        for i, text in enumerate(['Sets direction', 'Listens', 'Decides']):
            Question.objects.create(section=section, question_text=text, question_type='rating', order=i,
                                    config={'min': 1, 'max': 5}, labels={})
        Question.objects.create(section=section, question_text='Anything else?', question_type='text', order=3, config={})

    def test_renders_a_pdf_and_stores_nothing(self):
        before = (Organization.objects.count(), Report.objects.count())

        pdf = build_sample_pdf('en')

        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual((Organization.objects.count(), Report.objects.count()), before)

    def test_view_serves_and_caches_the_pdf(self):
        response = self.client.get(reverse('reports:sample_report_pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIsNotNone(cache.get('sample-report-pdf:en'))

    def test_without_the_shipped_questionnaire_it_is_not_found(self):
        Questionnaire.objects.all().delete()

        self.assertEqual(self.client.get(reverse('reports:sample_report_pdf')).status_code, 404)
