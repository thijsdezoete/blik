import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from core.models import Organization
from questionnaires.models import Question, Questionnaire, QuestionSection
from reports.models import Report
from reports.sample import SAMPLE_QUESTIONNAIRE, build_sample_pdf


class SampleReportTests(TestCase):
    def setUp(self):
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

    def test_the_command_writes_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.pdf'

            call_command('export_sample_pdf', str(path))

            self.assertTrue(path.read_bytes().startswith(b'%PDF'))

    def test_without_the_shipped_questionnaire_the_command_fails(self):
        Questionnaire.objects.all().delete()

        with self.assertRaises(CommandError):
            call_command('export_sample_pdf', '/nonexistent/sample.pdf')
