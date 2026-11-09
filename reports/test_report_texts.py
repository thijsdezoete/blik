"""Reports store codes and numbers; their texts are added in the reader's language when the report is shown."""
import copy
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import translation
from rest_framework.test import APIClient

from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from api.models import APIToken
from core.models import Organization
from questionnaires.models import (
    Question,
    QuestionSection,
    QuestionSectionTranslation,
    QuestionTranslation,
    Questionnaire,
)
from reports.report_texts import with_texts
from reports.services import generate_report
from reviews.models import Response, ReviewCycle, ReviewerToken

# A report of schema 2 as generate_report() stores it
CODES = {
    'schema': 2,
    'comparison': {
        'has_previous': True,
        'show_trends': True,
        'overall_trend': {'direction': 'up', 'change': 0.4},
        'section_trends': {'Collaboration': {'direction': 'slight_down', 'change': -0.2}},
    },
    'insights': {
        'perception_gaps': [
            {'type': 'overconfidence', 'severity': 'high', 'self_score': 4.46, 'others_score': 3.24, 'gap': 1.22},
        ],
        'overall_sentiment': {'score': 4.1, 'rating': 'excellent', 'based_on': 'others', 'self_avg': 4.46},
        'skill_profile': {'skill_level': 4.0, 'stage': 4, 'confidence': 1.0, 'contributing_questions': ['1']},
        'agency_profile': {'agency_level': 4.0, 'stage': 4, 'confidence': 1.0, 'contributing_questions': ['2']},
        'dreyfus_quadrant': {'quadrant_key': 'force_multiplier', 'skill_level': 4.0, 'agency_level': 4.0},
        'development_plan': {
            'agency_hint': 'take_initiative',
            'action_items': [{'question_id': 1, 'key': 'pairing', 'text': 'Pair with a colleague every week'}],
        },
    },
}


class ReportTextsTest(TestCase):

    def setUp(self):
        self.questionnaire = Questionnaire.objects.create(name='Skills')

    def test_the_codes_become_the_english_texts_reports_stored_before(self):
        with translation.override('en'):
            data = with_texts(CODES, self.questionnaire)

        trend = data['comparison']['overall_trend']
        section_trend = data['comparison']['section_trends']['Collaboration']
        self.assertEqual((trend['symbol'], trend['label']), ('↑', 'Improved'))
        self.assertEqual((section_trend['symbol'], section_trend['label']), ('↘', 'Slightly declined'))

        [gap] = data['insights']['perception_gaps']
        self.assertEqual(gap['message'], "Self-assessment (4.5) higher than others' perception (3.2)")
        self.assertEqual(gap['interpretation'], 'Opportunity to align self-perception with team feedback')
        self.assertEqual(data['insights']['overall_sentiment']['rating'], 'Excellent')

        skill = data['insights']['skill_profile']
        self.assertEqual((skill['skill_stage'], skill['stage_key']), ('Proficient', 'proficient'))
        self.assertEqual(skill['stage_info']['next_stage'], 'Expert')
        self.assertEqual(skill['stage_info']['development_focus'][0], 'Trust your intuition based on deep experience')

        agency = data['insights']['agency_profile']
        self.assertEqual((agency['agency_stage'], agency['description']), (
            'Proactive', 'Regularly proposes improvements and drives change'))
        self.assertEqual(data['insights']['dreyfus_quadrant']['name'], 'Force Multiplier')

        plan = data['insights']['development_plan']
        self.assertEqual(plan['primary_focus'], (
            'Deepen intuition through extensive practice and begin creating novel approaches.'))
        self.assertEqual(plan['quick_wins'][:3], [
            'Take more initiative on projects - your skills are ready for more ownership',
            'Pair with a colleague every week',
            'Mentor someone less experienced',
        ])
        next_capabilities = 'Develop capabilities of a Expert: Intuitive, creates new approaches'
        self.assertEqual(plan['long_term_goals'][0], next_capabilities)
        self.assertEqual(plan['next_level_requirements'], skill['stage_info']['development_focus'])

    def test_the_stored_codes_stay_untouched(self):
        with_texts(CODES, self.questionnaire)

        self.assertNotIn('label', CODES['comparison']['overall_trend'])
        self.assertEqual(CODES['insights']['overall_sentiment']['rating'], 'excellent')

    def test_a_report_of_schema_1_keeps_its_english_texts(self):
        report_data = {'insights': {
            'overall_sentiment': {'score': 4.1, 'rating': 'Excellent'},
            'skill_profile': {'skill_level': 2.0, 'skill_stage': 'Advanced Beginner', 'stage_info': {'name': 'x'}},
        }}

        with translation.override('de'):
            data = with_texts(report_data, self.questionnaire)

        self.assertEqual(data['insights']['overall_sentiment']['rating'], 'Excellent')
        self.assertEqual(data['insights']['skill_profile']['skill_stage'], 'Advanced Beginner')
        self.assertEqual(data['insights']['skill_profile']['stage_key'], 'advanced_beginner')


class TrendChangeTest(TestCase):

    def render(self):
        questionnaire = Questionnaire.objects.create(name='Skills')
        report_data = with_texts({
            'schema': 2,
            'insights': {'overall_sentiment': {'score': 4.1, 'rating': 'excellent'}},
            'section_summary': {'Collaboration': {'peer': 4.2}},
            'comparison': {
                'show_trends': True,
                'overall_trend': {'direction': 'up', 'change': 0.43},
                'section_trends': {'Collaboration': {'direction': 'slight_down', 'change': -0.18}},
            },
        }, questionnaire)
        cycle = SimpleNamespace(organization=SimpleNamespace(min_responses_for_anonymity=3))

        return render_to_string('reports/_report_content.html', {
            'report': SimpleNamespace(report_data=report_data),
            'report_data': report_data,
            'display_data': report_data,
            'cycle': cycle,
        })

    def test_the_change_shows_with_its_sign(self):
        with translation.override('en'):
            html = self.render()

        self.assertIn('(+0.4)', html)
        self.assertIn('↘ -0.2', html)

    def test_scores_are_coloured_and_labelled_by_the_overall_rating(self):
        with translation.override('en'):
            html = self.render()

        self.assertIn('progress-bar-fill score-excellent', html)
        self.assertIn('<span class="score-excellent" style="font-weight: 500;">Excellent (4.0-4.4)</span>', html)

    def test_numbers_follow_the_language(self):
        with translation.override('de'):
            html = self.render()

        self.assertIn('(+0,4)', html)
        self.assertIn('↘ -0,2', html)
        # CSS needs a decimal point, so the bar widths stay whole numbers
        self.assertIn('style="width: 82%;"', html)
        self.assertIn('style="width: 84%;"', html)


class GeneratedReportTest(TestCase):

    def setUp(self):
        ensure_permission_groups()
        # The two peers below are enough to show their scores, so the page shows every text
        self.organization = Organization.objects.create(
            name='Acme', email='org@acme.example', min_responses_for_anonymity=2,
        )
        self.admin = User.objects.create_user('admin', 'admin@acme.example', 'pw')
        UserProfile.objects.create(user=self.admin, organization=self.organization)
        assign_organization_admin(self.admin)

        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=self.organization)
        self.section = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Growth')
        self.skill = skill = self.create_question(self.section, 'Solves problems', {'skill': 1.0})
        agency = self.create_question(self.section, 'Takes initiative', {'agency': 1.0})
        reviewee = Reviewee.objects.create(name='Dana', email='dana@acme.example', organization=self.organization)
        self.cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=self.questionnaire)

        for category, rating in [('self', 2), ('peer', 4), ('peer', 4)]:
            token = ReviewerToken.objects.create(cycle=self.cycle, category=category)

            for question in [skill, agency]:
                Response.objects.create(
                    cycle=self.cycle,
                    question=question,
                    token=token,
                    category=category,
                    answer_data={'value': rating},
                )

        self.report = generate_report(self.cycle)

    @staticmethod
    def create_question(section, text, dreyfus_mapping):
        return Question.objects.create(
            section=section,
            question_text=text,
            question_type='rating',
            config={'min': 1, 'max': 5, 'dreyfus_mapping': dreyfus_mapping},
            labels={'1': 'Poor', '5': 'Excellent'},
            action_items=[{'key': 'practice', 'text': f'Practice: {text}', 'threshold': 5}],
            order=section.questions.count(),
        )

    def translate(self):
        QuestionSectionTranslation.objects.create(section=self.section, language='de', title='Wachstum')
        QuestionTranslation.objects.create(
            question=self.skill,
            language='de',
            question_text='Löst Probleme',
            labels={'5': 'Hervorragend'},
            action_items={'practice': 'Täglich üben'},
        )

    def test_a_report_stores_codes_instead_of_texts(self):
        insights = self.report.report_data['insights']

        self.assertEqual(self.report.report_data['schema'], 2)
        self.assertEqual(insights['skill_profile']['stage'], 4)
        self.assertNotIn('skill_stage', insights['skill_profile'])
        self.assertEqual(insights['overall_sentiment']['rating'], 'excellent')
        [gap] = insights['perception_gaps']
        self.assertEqual(gap['type'], 'imposter_syndrome')
        self.assertNotIn('interpretation', gap)
        self.assertEqual(insights['dreyfus_quadrant']['quadrant_key'], 'force_multiplier')

    def test_the_report_page_shows_the_texts(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse('reports:view_report', args=[self.cycle.uuid]))

        self.assertContains(page, 'Proficient')
        self.assertContains(page, 'Force Multiplier')
        self.assertContains(page, 'Strong performance but may undervalue own contributions')
        self.assertContains(page, 'data-current-stage="proficient"')

    def test_the_api_returns_the_texts(self):
        token = APIToken.objects.create(organization=self.organization, created_by=self.admin, name='T')
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {token.raw_token}')

        response = api.get(f'/api/v1/reports/{self.report.uuid}/')

        insights = response.json()['report_data']['insights']
        self.assertEqual(insights['skill_profile']['skill_stage'], 'Proficient')
        self.assertEqual(insights['overall_sentiment']['rating'], 'Excellent')

    def test_the_questionnaire_texts_follow_the_reader(self):
        self.translate()

        with translation.override('de'):
            data = with_texts(self.report.report_data, self.questionnaire)

        section = data['by_section'][f'{self.section.id}']
        skill = section['questions'][f'{self.skill.id}']
        [agency] = [question for question in section['questions'].values() if question is not skill]
        self.assertEqual(section['title'], 'Wachstum')
        self.assertEqual(skill['question_text'], 'Löst Probleme')
        self.assertEqual(skill['labels'], {'1': 'Poor', '5': 'Hervorragend'})
        self.assertEqual(agency['question_text'], 'Takes initiative')
        self.assertEqual(list(data['section_summary']), ['Wachstum'])
        self.assertEqual(list(data['charts']['section_scores']), ['Wachstum'])
        self.assertEqual([strength['area'] for strength in data['insights']['strengths']], ['Wachstum'])
        self.assertIn('Täglich üben', data['insights']['development_plan']['quick_wins'])

    def test_the_first_name_replaces_the_placeholder(self):
        data = copy.deepcopy(self.report.report_data)
        skill = data['by_section'][f'{self.section.id}']['questions'][f'{self.skill.id}']
        skill['question_text'] = 'Does {name} solve problems?'

        for item in data['insights']['development_plan']['action_items']:
            item['text'] = 'Pair {name} with a colleague'

        with translation.override('en'):
            data = with_texts(data, self.questionnaire, 'Dana Doe')

        skill = data['by_section'][f'{self.section.id}']['questions'][f'{self.skill.id}']
        self.assertEqual(skill['question_text'], 'Does Dana solve problems?')
        self.assertIn('Pair Dana with a colleague', data['insights']['development_plan']['quick_wins'])

    def test_the_source_language_shows_the_stored_texts(self):
        self.translate()
        self.skill.question_text = 'Solves problems well'
        self.skill.save()

        with translation.override('en'):
            data = with_texts(self.report.report_data, self.questionnaire)

        skill = data['by_section'][f'{self.section.id}']['questions'][f'{self.skill.id}']
        self.assertEqual(skill['question_text'], 'Solves problems')

    def test_a_deleted_question_keeps_its_stored_text(self):
        self.translate()
        self.skill.delete()

        with translation.override('de'):
            data = with_texts(self.report.report_data, self.questionnaire)

        questions = data['by_section'][f'{self.section.id}']['questions']
        self.assertIn('Solves problems', [question['question_text'] for question in questions.values()])

    def test_the_report_page_is_in_the_readers_language(self):
        self.translate()
        self.admin.profile.language = 'de'
        self.admin.profile.save()
        self.client.force_login(self.admin)

        page = self.client.get(reverse('reports:view_report', args=[self.cycle.uuid]))

        self.assertContains(page, 'Löst Probleme')
        self.assertContains(page, 'Wachstum')
        self.assertContains(page, 'class="report-language-switcher"')
        self.assertNotContains(page, 'Solves problems')

    def test_the_api_returns_the_questionnaire_texts_in_the_language_asked_for(self):
        self.translate()
        token = APIToken.objects.create(organization=self.organization, created_by=self.admin, name='T')
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {token.raw_token}')

        response = api.get(f'/api/v1/reports/{self.report.uuid}/?lang=de')

        section = response.json()['report_data']['by_section'][f'{self.section.id}']
        self.assertEqual(section['title'], 'Wachstum')
