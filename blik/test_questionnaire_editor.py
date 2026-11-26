"""The editor page changes topics and settings without a page load and answers the parts of the page to show again."""

import json
import re

from django.contrib.auth.models import User
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization
from questionnaires.answer_options import save_options
from questionnaires.editor import example_score, save_question, set_weight, translated_into
from questionnaires.models import (
    AnswerOptionTranslation, Question, QuestionSection, QuestionTranslation, Questionnaire, QuestionnaireTranslation,
)
from reviews.models import Response, ReviewCycle, ReviewerToken


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


LABELS = {
    '1': 'Needs clear direction',
    '2': 'Handles routine problems',
    '3': 'Solves problems independently',
    '4': 'Handles complex situations',
    '5': 'Expert problem solver',
}


class EditorQuestionTests(TestCase):

    def setUp(self):
        ensure_permission_groups()
        self.organization = Organization.objects.create(name='Acme', email='org@acme.example')
        admin = User.objects.create_user('admin', 'admin@acme.example', 'pw')
        UserProfile.objects.create(user=admin, organization=self.organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        self.q = Questionnaire.objects.create(
            name='Team lead 360', organization=self.organization, source_language='en',
        )
        self.section = QuestionSection.objects.create(questionnaire=self.q, title='Problem solving', order=0)
        self.question = Question.objects.create(
            section=self.section, question_text='How well does {name} solve problems?', question_type='rating',
            config={'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1.5}}, labels=LABELS, order=0,
        )

    def url(self):
        return reverse('questionnaire_edit', args=[self.q.uuid])

    def post(self, **fields):
        return self.client.post(self.url(), fields)

    def open(self, **params):
        return self.client.get(self.url(), params).json()['html']

    def labels(self):
        return {f'rating_label_{value}': label for value, label in LABELS.items()}

    def answer(self, question):
        reviewee = Reviewee.objects.create(name='Rita', email='rita@acme.example', organization=self.organization)
        cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=self.q)
        token = ReviewerToken.objects.create(cycle=cycle, category='peer')
        Response.objects.create(cycle=cycle, question=question, token=token, category='peer', answer_data={'value': 4})

    def test_a_new_question_is_stored_with_its_first_text(self):
        saved = self.post(
            action='save_question', section_id=self.section.id, question_text='Listens well', question_type='rating',
            rating_count='5', required='on',
        ).json()

        question = Question.objects.get(id=saved['question_id'])
        self.assertEqual(question.section, self.section)
        self.assertEqual(question.question_text, 'Listens well')
        self.assertIn('row_html', saved)

    def test_a_save_answers_everything_the_page_must_show_again(self):
        slots = self.post(
            action='save_question', question_id=self.question.id, question_text='Explains decisions',
            question_type='text',
        ).json()['slots']

        for name in (f'question-{self.question.id}-row', f'question-{self.question.id}-report',
                     f'topic-{self.section.id}-head', 'report-card', 'langs', 'reviewer', 'report'):
            self.assertIn(name, slots)

    def test_a_refused_save_changes_nothing_and_says_why(self):
        self.answer(self.question)

        response = self.post(
            action='save_question', question_id=self.question.id, question_text='How well does {name} decide?',
            question_type='rating', rating_count='4', **self.labels(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        self.assertTrue(response.json()['message'])
        self.question.refresh_from_db()
        self.assertEqual(self.question.config['max'], 5)
        self.assertEqual(self.question.question_text, 'How well does {name} solve problems?')

    def test_an_emptied_text_keeps_the_stored_text(self):
        response = self.post(
            action='save_question', question_id=self.question.id, question_text='  ', question_type='rating',
            rating_count='5', **self.labels(),
        )

        self.assertEqual(response.status_code, 400)
        self.question.refresh_from_db()
        self.assertEqual(self.question.question_text, 'How well does {name} solve problems?')

    def test_a_question_of_another_organization_is_not_found(self):
        other = Organization.objects.create(name='Other', email='org@other.acme.example')
        questionnaire = Questionnaire.objects.create(name='Other 360', organization=other)
        section = QuestionSection.objects.create(questionnaire=questionnaire, title='Theirs', order=0)
        theirs = Question.objects.create(
            section=section, question_text='Theirs', question_type='rating', config={'min': 1, 'max': 5},
        )

        saved = self.post(
            action='save_question', question_id=theirs.id, question_text='Mine', question_type='rating',
            rating_count='5',
        )
        added = self.post(
            action='save_question', section_id=section.id, question_text='Mine', question_type='rating',
            rating_count='5',
        )
        deleted = self.post(action='delete_question', question_id=theirs.id)
        opened = self.client.get(self.url(), {'question': theirs.id})
        opened_new = self.client.get(self.url(), {'new_in': section.id})

        for response in (saved, added, deleted, opened, opened_new):
            self.assertIn(response.status_code, (400, 404))

        theirs.refresh_from_db()
        self.assertEqual(theirs.question_text, 'Theirs')
        self.assertEqual(section.questions.count(), 1)

    def test_broken_values_are_refused_not_an_error(self):
        broken = [
            {'question_id': 'abc'},
            {'question_id': ''},
            {'rating_count': '9'},
            {'question_type': 'scale', 'scale_min': 'low'},
            {'question_type': 'single_choice', 'choice_option_id': [''], 'choice_option_label': ['x' * 300]},
            {'skill_weight': '3'},
        ]

        for fields in broken:
            with self.subTest(fields=fields):
                response = self.post(**{
                    'action': 'save_question', 'question_id': self.question.id, 'question_text': 'Changed',
                    'question_type': 'rating', 'rating_count': '5', **fields,
                })

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()['ok'])
                self.question.refresh_from_db()
                self.assertEqual(self.question.question_text, 'How well does {name} solve problems?')

        for params in ({'question': 'abc'}, {'new_in': ''}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url(), params).status_code, 400)

    def test_a_question_is_deleted(self):
        answer = self.post(action='delete_question', question_id=self.question.id).json()

        self.assertTrue(answer['ok'])
        self.assertIn(f'topic-{self.section.id}-head', answer['slots'])
        self.assertFalse(Question.objects.filter(id=self.question.id).exists())

    def test_the_open_question_asks_only_when_something_is_lost(self):
        html = self.open(question=self.question.id)

        self.assertNotIn('data-ask="type"', html)
        self.assertNotIn('data-ask="count"', html)
        self.assertIn('data-ask="delete"', html)

        self.answer(self.question)
        html = self.open(question=self.question.id)

        self.assertIn('data-ask="type"', html)
        self.assertRegex(html, r'<select[^>]*name="rating_count"[^>]*disabled')
        # The stored number is still posted, and a Slider cannot be chosen
        self.assertRegex(html, r'<input type="hidden" name="rating_count" value="5">')
        self.assertRegex(html, r'<input[^>]*value="scale"[^>]*disabled')

    def test_a_translated_label_asks_before_fewer_options(self):
        QuestionTranslation.objects.create(question=self.question, language='de', labels={'5': 'Experte'})

        html = self.open(question=self.question.id)

        self.assertIn('data-ask="count"', html)
        self.assertIn('data-ask="type"', html)

    def test_the_open_question_names_every_language_it_is_translated_into(self):
        QuestionTranslation.objects.create(question=self.question, language='de', question_text='Wie gut löst {name}?')

        html = self.open(question=self.question.id)

        # Only the question text is translated: a change of type loses nothing, so it does not ask
        self.assertIn('Translated into Deutsch (Sie)', html)
        self.assertNotIn('data-ask="type"', html)

    def test_a_new_question_offers_did_not_observe_unless_all_questions_are_without(self):
        def box(html):
            return re.search(r'<input[^>]*name="did_not_observe"[^>]*>', html)[0]

        self.assertIn('checked', box(self.open(new_in=self.section.id)))

        self.post(action='set_did_not_observe', on='')

        self.assertNotIn('checked', box(self.open(new_in=self.section.id)))

    def test_the_advice_is_in_the_form_only_with_its_marker(self):
        self.assertIn('name="action_items_posted"', self.open(question=self.question.id))

        self.question.config = {'min': 1, 'max': 5}
        self.question.save()

        self.assertNotIn('name="action_items_posted"', self.open(question=self.question.id))


class SaveQuestionTests(TestCase):
    """What the question dialog of the old editor kept, through save_question."""

    def setUp(self):
        organization = Organization.objects.create(name='Acme', email='org@acme.example')
        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=organization)
        section = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Problem solving')
        self.question = Question.objects.create(
            section=section,
            question_text='How effectively does {name} solve problems?',
            question_type='rating',
            config={'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1.5}},
            labels=LABELS,
        )

    def save(self, **fields):
        post = QueryDict(mutable=True)

        for name, value in {'required': 'on', **fields}.items():
            post.setlist(name, value if isinstance(value, list) else [value])

        save_question(self.questionnaire, post, self.question)
        self.question.refresh_from_db()

    def test_fixing_the_text_keeps_the_labels_and_the_weights(self):
        labels = {f'rating_label_{value}': label for value, label in LABELS.items()}

        self.save(
            question_type='rating', rating_count='5', question_text='How well does {name} solve problems?', **labels,
        )

        self.assertEqual(self.question.question_text, 'How well does {name} solve problems?')
        self.assertEqual(self.question.labels, LABELS)
        self.assertEqual(self.question.config['dreyfus_mapping'], {'skill': 1.5})

    def test_another_type_drops_the_labels_but_keeps_the_weights(self):
        self.save(
            question_type='likert',
            question_text=self.question.question_text,
            likert_option_id=['', ''],
            likert_option_label=['Never', 'Often'],
        )

        self.assertEqual(list(self.question.options.values_list('label', flat=True)), ['Never', 'Often'])
        self.assertEqual(self.question.labels, {})
        self.assertEqual(self.question.config['dreyfus_mapping'], {'skill': 1.5})

    def test_a_save_keeps_a_weight_stored_after_the_question_was_loaded(self):
        stale = Question.objects.get(pk=self.question.pk)
        set_weight(Question.objects.get(pk=self.question.pk), 'skill', 2)

        save_question(self.questionnaire, QueryDict(
            'question_type=rating&rating_count=5&question_text=Solves+problems&required=on'
        ), stale)

        self.assertEqual(Question.objects.get(pk=self.question.pk).config['dreyfus_mapping'], {'skill': 2.0})

    def test_two_weights_set_on_two_loaded_copies_are_both_stored(self):
        first, second = Question.objects.get(pk=self.question.pk), Question.objects.get(pk=self.question.pk)

        set_weight(first, 'skill', 2)
        set_weight(second, 'agency', 0.5)

        self.assertEqual(
            Question.objects.get(pk=self.question.pk).config['dreyfus_mapping'], {'skill': 2.0, 'agency': 0.5},
        )


class TranslatedIntoTests(TestCase):

    def test_the_languages_of_the_translated_labels_descriptions_and_answers(self):
        organization = Organization.objects.create(name='Acme', email='org@acme.example')
        questionnaire = Questionnaire.objects.create(name='Skills', organization=organization)
        section = QuestionSection.objects.create(questionnaire=questionnaire, title='Problem solving')
        rating = Question.objects.create(
            section=section, question_text='Solves problems', question_type='rating', config={'max': 5},
            labels=LABELS, order=0,
        )
        likert = Question.objects.create(section=section, question_text='Shares', question_type='likert', order=1)
        save_options(likert, [(None, 'Never', None), (None, 'Often', None)])
        QuestionTranslation.objects.create(question=rating, language='de', question_text='Löst Probleme')
        QuestionTranslation.objects.create(question=rating, language='nl', descriptions={'1': 'Weinig'})
        AnswerOptionTranslation.objects.create(option=likert.options.first(), language='de', label='Nie')
        AnswerOptionTranslation.objects.create(option=likert.options.last(), language='nl', label='')

        # The question text alone does not count, nor an empty translation
        self.assertEqual(translated_into(rating), ['Nederlands'])
        self.assertEqual(translated_into(likert), ['Deutsch (Sie)'])


class EditorReportCardTests(TestCase):
    """The card "The report": which models are on, and how much each question counts for them."""

    def setUp(self):
        ensure_permission_groups()
        self.organization = Organization.objects.create(name='Acme', email='org@acme.example')
        admin = User.objects.create_user('admin', 'admin@acme.example', 'pw')
        UserProfile.objects.create(user=admin, organization=self.organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        self.q = Questionnaire.objects.create(name='Team lead 360', organization=self.organization)
        self.section = QuestionSection.objects.create(questionnaire=self.q, title='Problem solving', order=0)
        self.question = Question.objects.create(
            section=self.section, question_text='How well does {name} solve problems?', question_type='rating',
            config={'min': 1, 'max': 5}, order=0,
        )

    def post(self, **fields):
        return self.client.post(reverse('questionnaire_edit', args=[self.q.uuid]), fields)

    def config(self, question=None):
        return Question.objects.get(id=(question or self.question).id).config

    def test_a_weight_set_in_the_table_is_stored_and_shown(self):
        slots = self.post(
            action='set_weight', question_id=self.question.id, model='skill', weight='2', shown='skill',
        ).json()['slots']

        self.assertEqual(self.config()['dreyfus_mapping'], {'skill': 2.0})
        self.assertIn('report-card', slots)
        self.assertIn(f'question-{self.question.id}-report', slots)

    def test_a_weight_outside_the_five_is_refused(self):
        response = self.post(action='set_weight', question_id=self.question.id, model='skill', weight='3')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        self.assertNotIn('dreyfus_mapping', self.config())

    def test_a_request_that_does_not_come_from_the_page_changes_nothing(self):
        other = Organization.objects.create(name='Other', email='org@other.acme.example')
        questionnaire = Questionnaire.objects.create(name='Other 360', organization=other)
        section = QuestionSection.objects.create(questionnaire=questionnaire, title='Theirs', order=0)
        theirs = Question.objects.create(
            section=section, question_text='Theirs', question_type='rating', config={'min': 1, 'max': 5},
        )
        broken = [
            {'question_id': self.question.id, 'model': 'disc', 'weight': '1'},
            {'question_id': self.question.id, 'model': 'skill', 'weight': 'nan'},
            {'question_id': self.question.id, 'model': 'skill', 'weight': ''},
            {'question_id': 'abc', 'model': 'skill', 'weight': '1'},
            {'question_id': theirs.id, 'model': 'skill', 'weight': '1'},
        ]

        for fields in broken:
            with self.subTest(fields=fields):
                response = self.post(action='set_weight', **fields)

                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()['ok'])

        self.assertNotIn('dreyfus_mapping', self.config())
        self.assertNotIn('dreyfus_mapping', self.config(theirs))

        response = self.post(action='clear_model', model='disc')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

    def test_unticking_a_model_removes_its_weights_only(self):
        second = Question.objects.create(
            section=self.section, question_text='How often does {name} start an improvement?',
            question_type='rating', config={'min': 1, 'max': 5}, order=1,
        )

        for question in (self.question, second):
            question.config['dreyfus_mapping'] = {'skill': 1, 'agency': 1}
            question.save()

        answer = self.post(action='clear_model', model='skill', shown='agency').json()

        self.assertTrue(answer['ok'])
        self.assertIn('report-card', answer['slots'])
        self.assertEqual(self.config()['dreyfus_mapping'], {'agency': 1})
        self.assertEqual(self.config(second)['dreyfus_mapping'], {'agency': 1})

    def test_a_ticked_model_without_questions_gets_its_column(self):
        self.assertIn('name="agency_weight"', self.post(action='refresh', shown='agency').json()['slots']['report-card'])
        self.assertNotIn('name="agency_weight"', self.post(action='refresh').json()['slots']['report-card'])

    def test_unticking_asks_first_only_while_questions_count(self):
        card = self.post(action='refresh', shown='skill').json()['slots']['report-card']

        self.assertNotIn('data-ask="model-skill"', card)

        self.post(action='set_weight', question_id=self.question.id, model='skill', weight='0.5')
        card = self.post(action='refresh').json()['slots']['report-card']

        self.assertIn('data-ask="model-skill"', card)
        self.assertNotIn('data-ask="model-agency"', card)

    def test_a_question_without_a_score_is_not_in_the_table(self):
        Question.objects.create(
            section=self.section, question_text='What should {name} keep doing?', question_type='text', order=1,
        )

        card = self.post(action='refresh', shown='skill').json()['slots']['report-card']

        self.assertIn(f'data-question-id="{self.question.id}"', card)
        self.assertEqual(card.count('data-question-id='), 1)

    def test_how_a_level_is_made_shows_the_numbers_of_the_preview(self):
        self.post(action='set_weight', question_id=self.question.id, model='agency', weight='2')

        report = self.post(action='refresh').json()['slots']['report']
        score = example_score(self.question)

        self.assertIn(f'({score:.1f} x 2) / 2 = {score:.2f}<', report)
        self.assertIn('<td>Counts double</td>', report)
        self.assertIn('data-level="agency"', report)
        self.assertNotIn('data-level="skill"', report)
        self.assertIn(' is stage ', report)

    def test_an_older_weight_outside_the_five_shows_with_its_number(self):
        self.question.config['dreyfus_mapping'] = {'skill': 0.75}
        self.question.save()

        slots = self.post(action='refresh').json()['slots']
        score = example_score(self.question)

        self.assertRegex(slots['report-card'], r'<option value="0.75" selected>Counts 0.75 times</option>')
        self.assertIn(f'({score:.1f} x 0.75) / 0.75 = ', slots['report'])
        self.assertIn('<td>Counts 0.75 times</td>', slots['report'])

    def test_unticking_asks_only_about_questions_with_a_score(self):
        Question.objects.create(
            section=self.section, question_text='What should {name} keep doing?', question_type='text',
            config={'dreyfus_mapping': {'skill': 1}}, order=1,
        )

        card = self.post(action='refresh').json()['slots']['report-card']

        # The model is on through the old weight, but no question in the table counts
        self.assertIn('data-model="skill" checked', card)
        self.assertNotIn('data-ask="model-skill"', card)

    def test_an_open_question_that_is_no_id_is_ignored(self):
        for action in ('refresh', 'set_weight'):
            with self.subTest(action=action):
                response = self.post(
                    action=action, open='\u00b2', question_id=self.question.id, model='skill', weight='1',
                )

                self.assertEqual(response.status_code, 200)
                self.assertNotIn('question-\u00b2-report', response.json()['slots'])
