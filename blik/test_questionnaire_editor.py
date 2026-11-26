"""The editor page changes topics and settings without a page load and answers the parts of the page to show again."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization
from questionnaires.models import Question, QuestionSection, Questionnaire, QuestionnaireTranslation


class EditorTopicTests(TestCase):

    def setUp(self):
        ensure_permission_groups()
        organization = Organization.objects.create(name='Acme', email='org@acme.example')
        admin = User.objects.create_user('admin', 'admin@acme.example', 'pw')
        UserProfile.objects.create(user=admin, organization=organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        self.q = Questionnaire.objects.create(name='Team lead 360', organization=organization, source_language='en')
        self.section = QuestionSection.objects.create(questionnaire=self.q, title='Communication', order=0)
        self.rating = Question.objects.create(
            section=self.section, question_text='How clearly does {name} explain a decision?',
            question_type='rating', config={'min': 1, 'max': 5}, order=0,
        )

    def post(self, **fields):
        return self.client.post(reverse('questionnaire_edit', args=[self.q.uuid]), fields)

    def add_scored_topic(self, title, order):
        section = QuestionSection.objects.create(questionnaire=self.q, title=title, order=order)
        Question.objects.create(section=section, question_text='Score', question_type='rating', config={'max': 5})

        return section

    def test_a_topic_is_added_changed_and_deleted_without_a_page(self):
        added = self.post(action='add_section').json()

        self.assertTrue(added['ok'])
        section = QuestionSection.objects.get(id=added['section_id'])
        self.assertEqual(section.title, 'New topic')
        self.assertIn(f'data-section="{section.id}"', added['html'])

        changed = self.post(action='save_section', section_id=section.id, title='Leadership', description='').json()

        self.assertIn(f'topic-{section.id}-head', changed['slots'])
        self.assertIn('reviewer', changed['slots'])
        section.refresh_from_db()
        self.assertEqual(section.title, 'Leadership')

        self.post(action='delete_section', section_id=section.id)

        self.assertFalse(QuestionSection.objects.filter(id=section.id).exists())

    def test_a_topic_needs_a_title(self):
        response = self.post(action='save_section', section_id=self.section.id, title='  ', description='')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        self.section.refresh_from_db()
        self.assertEqual(self.section.title, 'Communication')

    def test_the_answer_says_which_case_the_radar_is(self):
        self.assertIsNone(self.post(action='refresh').json()['chart']['axes'])

        self.add_scored_topic('Collaboration', 1)
        self.add_scored_topic('Leadership', 2)

        self.assertEqual(len(self.post(action='refresh').json()['chart']['axes']), 3)

    def test_another_organizations_topic_cannot_be_changed(self):
        other = Organization.objects.create(name='Other', email='org@other.acme.example')
        questionnaire = Questionnaire.objects.create(name='Other 360', organization=other)
        section = QuestionSection.objects.create(questionnaire=questionnaire, title='Theirs', order=0)

        changed = self.post(action='save_section', section_id=section.id, title='Mine', description='')
        deleted = self.post(action='delete_section', section_id=section.id)

        self.assertIn(changed.status_code, (400, 404))
        self.assertIn(deleted.status_code, (400, 404))
        section.refresh_from_db()
        self.assertEqual(section.title, 'Theirs')

    def test_the_switch_for_did_not_observe_sets_every_question(self):
        answer = self.post(action='set_did_not_observe', on='').json()

        self.rating.refresh_from_db()
        self.assertIs(self.rating.config['did_not_observe'], False)
        # Only the switch comes back, not the fields of the settings that may be typed in
        self.assertIn('did-not-observe', answer['slots'])
        self.assertNotIn('settings', answer['slots'])

    def test_the_original_language_cannot_become_a_translated_one(self):
        QuestionnaireTranslation.objects.create(questionnaire=self.q, language='de', name='Teamleitung 360')

        answer = self.post(
            action='save_info', name='Team lead 360', description='', source_language='de', is_default='',
        ).json()

        self.assertFalse(answer['ok'])
        self.assertTrue(answer['message'])
        self.q.refresh_from_db()
        self.assertEqual(self.q.source_language, 'en')

    def test_a_new_order_is_stored_and_answered(self):
        second = self.add_scored_topic('Collaboration', 1)
        layout = [
            {'section': second.id, 'questions': [question.id for question in second.questions.all()]},
            {'section': self.section.id, 'questions': [self.rating.id]},
        ]

        answer = self.post(action='reorder', layout=json.dumps(layout)).json()

        self.assertTrue(answer['ok'])
        self.assertEqual(list(self.q.sections.values_list('title', flat=True)), ['Collaboration', 'Communication'])
        self.assertIn(f'topic-{second.id}-head', answer['slots'])
        self.assertIn(f'topic-{self.section.id}-head', answer['slots'])
        self.assertIn('reviewer', answer['slots'])

    def test_a_broken_request_is_refused_not_an_error(self):
        # A whole layout, but with the topic's id as a float
        float_layout = [{'section': float(self.section.id), 'questions': [self.rating.id]}]
        broken = [
            {'action': 'reorder', 'layout': json.dumps(float_layout)},
            {'action': 'reorder', 'layout': 'null'},
            {'action': 'save_section', 'section_id': 'abc', 'title': 'Mine', 'description': ''},
            {'action': 'save_section', 'title': 'Mine', 'description': ''},
        ]

        for fields in broken:
            with self.subTest(fields=fields):
                response = self.post(**fields)

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()['ok'])
                self.section.refresh_from_db()
                self.assertEqual((self.section.title, self.section.order), ('Communication', 0))
