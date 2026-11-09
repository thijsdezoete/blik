"""
Safety net for the questionnaire rework: a questionnaire built in the editor, answered through the
feedback form and the API, and read in the report.

The tests only look at what people see, the labels in the editor, the form and the report. They pick
answers by their label and send whatever value the form offers for it, so they keep holding while
the storage of options, answers and report data changes underneath.
"""
import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.factories import RevieweeFactory
from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from api.models import APIToken
from core.models import Organization
from questionnaires.models import Question, Questionnaire
from reports.models import Report
from reports.services import generate_report
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory

DEFAULT_LIKERT = ['Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree']


def option_rows(prefix, labels, weights=()):
    """The answer option rows the editor posts for new options."""

    rows = {f'{prefix}_option_id': [''] * len(labels), f'{prefix}_option_label': labels}

    if weights:
        rows[f'{prefix}_option_weight'] = weights

    return rows


class FormChoices(HTMLParser):
    """The options the feedback form offers, as {field name: {label: value}}."""

    def __init__(self):
        super().__init__()
        self.inputs = {}
        self.labels = {}
        self.options = {}
        self.label_for = None
        self.select = None
        self.option_value = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == 'input' and attrs.get('type') in ('radio', 'checkbox'):
            self.inputs[attrs['id']] = (attrs['name'], attrs['value'])
        elif tag == 'label' and attrs.get('for'):
            self.label_for, self.text = attrs['for'], []
        elif tag == 'select':
            self.select = attrs['name']
        elif tag == 'option' and self.select:
            self.option_value, self.text = attrs.get('value', ''), []

    def handle_data(self, data):
        self.text.append(data)

    def handle_endtag(self, tag):
        text = ' '.join(''.join(self.text).split())

        if tag == 'label' and self.label_for:
            self.labels[self.label_for] = text
            self.label_for = None
        elif tag == 'option' and self.option_value is not None:
            if self.option_value:
                self.options.setdefault(self.select, {})[text] = self.option_value
            self.option_value = None
        elif tag == 'select':
            self.select = None

    def choices(self):
        choices = {name: dict(options) for name, options in self.options.items()}

        for input_id, (name, value) in self.inputs.items():
            choices.setdefault(name, {})[self.labels.get(input_id, '')] = value

        return choices


def page_text(response):
    """The visible text of a page, whitespace collapsed."""
    html = re.sub(r'<(script|style)\b.*?</\1>', ' ', response.content.decode(), flags=re.S)
    return ' '.join(unescape(re.sub(r'<[^>]+>', ' ', html)).split())


class QuestionnaireFlowTests(TestCase):
    def setUp(self):
        # Submitting feedback is rate limited per IP; the limit counts in the cache
        cache.clear()
        ensure_permission_groups()
        self.organization = Organization.objects.create(name='Acme', email='org@acme.example')
        self.admin = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.organization)
        assign_organization_admin(self.admin)
        self.client.force_login(self.admin)

        self.questionnaire = self.build_questionnaire()
        questions = Question.objects.filter(section__questionnaire=self.questionnaire)
        self.questions = {question.question_text: question for question in questions}
        self.cycle = ReviewCycleFactory(
            reviewee=RevieweeFactory(organization=self.organization, name='Dana Doe'),
            questionnaire=self.questionnaire,
        )

    def edit(self, **data):
        return self.client.post(reverse('questionnaire_edit', args=[self.questionnaire.uuid]), data)

    def build_questionnaire(self):
        """Build a questionnaire with every question type the way the editor does."""
        self.client.post(reverse('questionnaire_create'), {'name': 'Safety Net'})
        self.questionnaire = Questionnaire.objects.get(name='Safety Net', organization=self.organization)
        self.edit(action='add_section', section_title='Collaboration')
        section_id = self.questionnaire.sections.get().id

        def add(question_type, text, **fields):
            self.edit(action='add_question', section_id=section_id, question_type=question_type,
                      question_text=text, required='on', **fields)

        add('rating', 'Shares knowledge', add_skill_weight='1.0',
            **{'add_action_items[0][text]': 'Pair with a colleague every week',
               'add_action_items[0][threshold]': '4.5'})
        add('likert', 'Gives useful feedback', **option_rows('likert', DEFAULT_LIKERT))
        add('likert', 'Asks for help', **option_rows('likert', ['Never', 'Sometimes', 'Often', 'Always']))
        add('single_choice', 'Seniority', enable_scoring='on',
            **option_rows('choice', ['Novice', 'Advanced', 'Expert'], ['1', '3', '5']))
        add('multiple_choice', 'Strong areas', **option_rows('choice', ['Code', 'Docs', 'Talks']))
        add('scale', 'Energy', scale_min='0', scale_max='10', scale_step='1',
            scale_min_label='Drained', scale_max_label='Energised')
        add('text', 'Anything else?')

        return self.questionnaire

    def answer_by_form(self, token, answers):
        """Fill in the feedback form, choosing options by their visible label."""
        form = self.client.get(reverse('reviews:feedback_form', args=[token.token]))
        parser = FormChoices()
        parser.feed(form.content.decode())
        choices = parser.choices()
        data = {}

        for text, answer in answers.items():
            field = f'question_{self.questions[text].id}'
            if isinstance(answer, list):
                data[field] = [choices[field][label] for label in answer]
            elif field in choices and answer in choices[field]:
                data[field] = choices[field][answer]
            else:
                data[field] = answer

        response = self.client.post(reverse('reviews:submit_feedback', args=[token.token]), data)
        self.assertEqual(response.status_code, 200, response.content)

    def report_text(self):
        generate_report(self.cycle)
        return page_text(self.client.get(reverse('reports:view_report', args=[self.cycle.uuid])))

    def question_text(self, report, question):
        """The part of the report that belongs to one question."""
        texts = list(self.questions)
        start = report.index(question)
        following = [report.find(other, start + len(question)) for other in texts if other != question]
        ends = [position for position in following if position > start]
        return report[start:min(ends)] if ends else report[start:]

    def peer_answers(self):
        return [
            {'Shares knowledge': '4', 'Gives useful feedback': 'Agree', 'Asks for help': 'Often',
             'Seniority': 'Advanced', 'Strong areas': ['Code', 'Docs'], 'Energy': '7',
             'Anything else?': 'Great mentor'},
            {'Shares knowledge': '5', 'Gives useful feedback': 'Strongly Agree', 'Asks for help': 'Often',
             'Seniority': 'Expert', 'Strong areas': ['Code'], 'Energy': '8',
             'Anything else?': 'Very reliable'},
            {'Shares knowledge': '4', 'Gives useful feedback': 'Neutral', 'Asks for help': 'Always',
             'Seniority': 'Advanced', 'Strong areas': ['Talks'], 'Energy': '9',
             'Anything else?': 'Keeps the team calm'},
        ]

    def test_the_editor_shows_every_question_and_its_options(self):
        response = self.client.get(reverse('questionnaire_edit', args=[self.questionnaire.uuid]))
        page = page_text(response)

        for text in ['Shares knowledge', 'Gives useful feedback', 'Asks for help', 'Seniority',
                     'Strong areas', 'Energy', 'Anything else?']:
            self.assertIn(text, page)
        self.assertIn('Gives useful feedback * Type: Likert Scale | 5-point scale', page)
        self.assertIn('Asks for help * Type: Likert Scale | 4-point scale', page)
        # The list shows the options only in the edit dialog, which the page fills from its markup
        for label in ['Sometimes', 'Often', 'Always', 'Novice', 'Advanced', 'Expert', 'Code', 'Docs', 'Talks']:
            self.assertContains(response, label)

    def test_the_form_offers_every_option_by_its_label(self):
        token = ReviewerTokenFactory(cycle=self.cycle, category='peer')
        form = self.client.get(reverse('reviews:feedback_form', args=[token.token]))
        parser = FormChoices()
        parser.feed(form.content.decode())
        choices = parser.choices()

        def labels(text):
            return set(choices[f'question_{self.questions[text].id}'])

        self.assertEqual(labels('Gives useful feedback'), set(DEFAULT_LIKERT))
        self.assertEqual(labels('Asks for help'), {'Never', 'Sometimes', 'Often', 'Always'})
        self.assertEqual(labels('Seniority'), {'Novice', 'Advanced', 'Expert'})
        self.assertEqual(labels('Strong areas'), {'Code', 'Docs', 'Talks'})
        self.assertEqual(labels('Shares knowledge'), {
            '1 Strongly Disagree', '2 Disagree', '3 Neutral', '4 Agree', '5 Strongly Agree',
            'Did not observe'})
        self.assertIn('Drained', page_text(form))
        self.assertIn('Energised', page_text(form))

    def test_the_report_counts_the_answers_given_in_the_form(self):
        for answers in self.peer_answers():
            self.answer_by_form(ReviewerTokenFactory(cycle=self.cycle, category='peer'), answers)

        report = self.report_text()

        rating = self.question_text(report, 'Shares knowledge')
        self.assertIn('4.33 / 5.0', rating)
        self.assertIn('5 - Strongly Agree 1 (33%)', rating)
        self.assertIn('4 - Agree 2 (67%)', rating)

        default_likert = self.question_text(report, 'Gives useful feedback')
        self.assertIn('Mostly positive: 67% (2 of 3 respondents)', default_likert)
        self.assertIn('Agree 1 respondent (33%)', default_likert)
        self.assertIn('Disagree 0 respondents (0%)', default_likert)

        custom_likert = self.question_text(report, 'Asks for help')
        self.assertIn('Often 2 respondents (67%)', custom_likert)
        self.assertIn('Always 1 respondent (33%)', custom_likert)
        self.assertIn('Never 0 respondents (0%)', custom_likert)

        single_choice = self.question_text(report, 'Seniority')
        self.assertIn('3.7 weighted avg', single_choice)
        self.assertIn('Advanced 2 respondents (67%)', single_choice)
        self.assertIn('Expert 1 respondent (33%)', single_choice)

        multiple_choice = self.question_text(report, 'Strong areas')
        self.assertIn('Code 2 of 3 respondents (67%)', multiple_choice)
        self.assertIn('Talks 1 of 3 respondents (33%)', multiple_choice)

        self.assertIn('8.0 / 10', self.question_text(report, 'Energy'))

        text = self.question_text(report, 'Anything else?')
        for answer in ['Great mentor', 'Very reliable', 'Keeps the team calm']:
            self.assertIn(answer, text)

    def test_the_report_shows_the_action_item_of_a_question_below_its_threshold(self):
        for answers in self.peer_answers():
            self.answer_by_form(ReviewerTokenFactory(cycle=self.cycle, category='peer'), answers)

        self.assertIn('Pair with a colleague every week', self.report_text())

    def test_the_self_assessment_is_reported_on_its_own(self):
        for answers in self.peer_answers():
            self.answer_by_form(ReviewerTokenFactory(cycle=self.cycle, category='peer'), answers)
        self.answer_by_form(ReviewerTokenFactory(cycle=self.cycle, category='self'), {
            'Shares knowledge': '2', 'Gives useful feedback': 'Disagree', 'Asks for help': 'Never',
            'Seniority': 'Novice', 'Strong areas': ['Docs'], 'Energy': '3', 'Anything else?': 'Self note',
        })

        report = self.report_text()

        self.assertIn('Self', self.question_text(report, 'Asks for help'))
        self.assertIn('Never 1 respondent (100%)', self.question_text(report, 'Asks for help'))
        self.assertIn('Self note', self.question_text(report, 'Anything else?'))

    def test_answers_sent_by_label_through_the_api_count_like_form_answers(self):
        for answers in self.peer_answers()[:2]:
            self.answer_by_form(ReviewerTokenFactory(cycle=self.cycle, category='peer'), answers)

        api_token = APIToken.objects.create(organization=self.organization, created_by=self.admin, name='Test')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {api_token.raw_token}')
        reviewer = ReviewerTokenFactory(cycle=self.cycle, category='peer')
        answers = {'Gives useful feedback': 'Neutral', 'Asks for help': 'Always', 'Seniority': 'Advanced',
                   'Strong areas': ['Talks']}
        response = client.post(f'/api/v1/cycles/{self.cycle.uuid}/submit_responses/', {
            'token': str(reviewer.token),
            'responses': [{'question_uuid': str(self.questions[text].uuid), 'value': value}
                          for text, value in answers.items()],
        }, format='json')
        self.assertIn(response.status_code, (200, 201), response.content)

        report = self.report_text()

        self.assertIn('Often 2 respondents (67%)', self.question_text(report, 'Asks for help'))
        self.assertIn('Always 1 respondent (33%)', self.question_text(report, 'Asks for help'))
        self.assertIn('Advanced 2 respondents (67%)', self.question_text(report, 'Seniority'))
        self.assertIn('Talks 1 of 3 respondents (33%)', self.question_text(report, 'Strong areas'))

    def test_a_report_generated_before_the_rework_reads_the_same(self):
        # report_data as generate_report wrote it before the rework, for the answers in peer_answers()
        # plus the self-assessment above. Existing reports are not regenerated, so it must still render.
        data = json.loads((Path(__file__).parent / 'testdata' / 'report_data_schema1.json').read_text())
        Report.objects.create(cycle=self.cycle, report_data=data)

        report = page_text(self.client.get(reverse('reports:view_report', args=[self.cycle.uuid])))

        self.assertIn('4 - Agree 2 (67%)', self.question_text(report, 'Shares knowledge'))
        self.assertIn('Mostly positive: 67% (2 of 3 respondents)', self.question_text(report, 'Gives useful feedback'))
        self.assertIn('Often 2 respondents (67%)', self.question_text(report, 'Asks for help'))
        self.assertIn('Never 1 respondent (100%)', self.question_text(report, 'Asks for help'))
        self.assertIn('3.7 weighted avg', self.question_text(report, 'Seniority'))
        self.assertIn('Code 2 of 3 respondents (67%)', self.question_text(report, 'Strong areas'))
        self.assertIn('8.0 / 10', self.question_text(report, 'Energy'))
        self.assertIn('Keeps the team calm', self.question_text(report, 'Anything else?'))
        self.assertIn('Pair with a colleague every week', report)
