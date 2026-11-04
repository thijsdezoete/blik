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

    def test_a_new_question_keys_its_items(self):
        self.edit(**{
            'action': 'add_question',
            'section_id': self.section.id,
            'question_type': 'text',
            'question_text': 'Notes',
            'add_action_items[0][text]': 'Write it down',
            'add_action_items[0][threshold]': '3',
        })

        [item] = Question.objects.get(question_text='Notes').action_items
        self.assertEqual(item['text'], 'Write it down')
        self.assertTrue(item['key'])

    def test_the_dreyfus_dialog_keeps_the_keys_and_keys_new_items(self):
        [item] = self.question.action_items
        item['key'] = 'pairing'
        self.question.save()

        self.edit(**{
            'action': 'update_dreyfus_config',
            'question_id': self.question.id,
            'skill_weight': '1',
            'agency_weight': '0',
            'action_items[0][key]': 'pairing',
            'action_items[0][text]': 'Pair every week',
            'action_items[0][threshold]': '3.5',
            'action_items[1][key]': '',
            'action_items[1][text]': 'Give a talk',
            'action_items[1][threshold]': '4',
        })

        self.question.refresh_from_db()
        first, second = self.question.action_items
        self.assertEqual((first['key'], first['text']), ('pairing', 'Pair every week'))
        self.assertTrue(second['key'])
        self.assertNotEqual(second['key'], 'pairing')

    def test_more_than_ten_items_keep_their_order(self):
        texts = [f'Step {i}' for i in range(12)]

        self.edit(action='add_question', section_id=self.section.id, question_type='text', question_text='Notes',
                  **{f'add_action_items[{i}][text]': text for i, text in enumerate(texts)})
        self.edit(action='update_dreyfus_config', question_id=self.question.id,
                  **{f'action_items[{i}][text]': text for i, text in enumerate(texts)})

        for question in Question.objects.get(question_text='Notes'), Question.objects.get(id=self.question.id):
            self.assertEqual([item['text'] for item in question.action_items], texts)

    def test_the_dreyfus_dialog_replaces_keys_the_question_does_not_have(self):
        self.edit(**{
            'action': 'update_dreyfus_config',
            'question_id': self.question.id,
            'action_items[0][key]': '"><img src=x onerror=alert(1)>',
            'action_items[0][text]': 'Pair weekly',
        })

        self.question.refresh_from_db()
        [item] = self.question.action_items
        self.assertRegex(item['key'], r'^[A-Za-z0-9]{8}$')
