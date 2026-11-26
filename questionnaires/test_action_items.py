"""Action items carry keys that translations of the items refer to."""
from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization
from core.upgrade_steps import key_action_items
from questionnaires.models import Question, QuestionSection, Questionnaire


class ActionItemKeyTests(TestCase):

    def setUp(self):
        ensure_permission_groups()
        organization = Organization.objects.create(name='Acme', email='org@acme.example')
        admin = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=admin, organization=organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=organization)
        self.section = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Growth')
        self.question = Question.objects.create(
            section=self.section,
            question_text='Shares knowledge',
            question_type='rating',
            action_items=[{'text': 'Pair weekly', 'threshold': 3.5}],
        )

    def edit(self, **data):
        return self.client.post(reverse('questionnaire_edit', args=[self.questionnaire.uuid]), data)

    def test_the_upgrade_step_keys_existing_items_once(self):
        key_action_items(StringIO())
        self.question.refresh_from_db()
        [item] = self.question.action_items

        key_action_items(StringIO())
        self.question.refresh_from_db()

        self.assertEqual(len(item['key']), 8)
        self.assertEqual(self.question.action_items, [item])

    def save_new(self, **data):
        return self.edit(action='save_question', section_id=self.section.id, question_type='text',
                         question_text='Notes', **data)

    def save_advice(self, lines):
        """Save the advice dialog of the question with the lines (text, key) in the row "Every stage"."""

        data = {'action': 'save_advice', 'question_id': self.question.id, 'threshold': '3.5', 'try_stage': '1',
                'try_score': '2.4'}

        for index, (text, key) in enumerate(lines):
            data.update({f'advice[{index}][text]': text, f'advice[{index}][key]': key, f'advice[{index}][stage]': ''})

        return self.edit(**data)

    def test_a_new_question_has_no_advice(self):
        self.save_new(**{'action_items[0][text]': 'Write it down', 'action_items[0][threshold]': '3'})

        self.assertEqual(Question.objects.get(question_text='Notes').action_items, [])

    def test_a_save_keeps_the_keys_and_keys_new_items(self):
        [item] = self.question.action_items
        item['key'] = 'pairing'
        self.question.save()

        self.save_advice([('Pair every week', 'pairing'), ('Give a talk', '')])

        self.question.refresh_from_db()
        first, second = self.question.action_items
        self.assertEqual((first['key'], first['text']), ('pairing', 'Pair every week'))
        self.assertTrue(second['key'])
        self.assertNotEqual(second['key'], 'pairing')

    def test_more_than_ten_items_keep_their_order(self):
        texts = [f'Step {i}' for i in range(12)]

        self.save_advice([(text, '') for text in texts])

        self.question.refresh_from_db()
        self.assertEqual([item['text'] for item in self.question.action_items], texts)

    def test_a_save_replaces_keys_the_question_does_not_have(self):
        self.save_advice([('Pair weekly', '"><img src=x onerror=alert(1)>')])

        self.question.refresh_from_db()
        [item] = self.question.action_items
        self.assertRegex(item['key'], r'^[A-Za-z0-9]{8}$')
