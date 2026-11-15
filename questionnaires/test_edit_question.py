"""Editing a question in the dashboard keeps what the edit dialog does not show."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization
from questionnaires.models import Question, QuestionSection, Questionnaire

LABELS = {
    '1': 'Needs clear direction',
    '2': 'Handles routine problems',
    '3': 'Solves problems independently',
    '4': 'Handles complex situations',
    '5': 'Expert problem solver',
}


class EditQuestionTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        organization = Organization.objects.create(name='Acme', email='org@acme.example')
        admin = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=admin, organization=organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=organization)
        section = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Problem solving')
        self.question = Question.objects.create(
            section=section,
            question_text='How effectively does this person solve problems?',
            question_type='rating',
            config={'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1.5}},
            labels=LABELS,
        )

    def edit(self, **fields):
        self.client.post(reverse('questionnaire_edit', args=[self.questionnaire.uuid]), {
            'action': 'edit_question', 'question_id': self.question.id, 'required': 'on', **fields,
        })
        self.question.refresh_from_db()

    def test_fixing_the_text_keeps_the_labels_and_the_dreyfus_weights(self):
        # The dialog shows the labels and posts them back
        page = self.client.get(reverse('questionnaire_edit', args=[self.questionnaire.uuid]))
        self.assertContains(page, 'Expert problem solver')
        labels = {f'rating_label_{value}': label for value, label in LABELS.items()}

        self.edit(question_type='rating', question_text='How well does this person solve problems?', **labels)

        self.assertEqual(self.question.question_text, 'How well does this person solve problems?')
        self.assertEqual(self.question.labels, LABELS)
        self.assertEqual(self.question.config['dreyfus_mapping'], {'skill': 1.5})

    def test_another_type_drops_the_rating_labels_but_keeps_the_dreyfus_weights(self):
        self.edit(
            question_type='likert',
            question_text=self.question.question_text,
            likert_option_id=['', ''],
            likert_option_label=['Never', 'Often'],
        )

        self.assertEqual(list(self.question.options.values_list('label', flat=True)), ['Never', 'Often'])
        self.assertEqual(self.question.labels, {})
        self.assertEqual(self.question.config['dreyfus_mapping'], {'skill': 1.5})

    def test_an_edit_keeps_the_chart_settings(self):
        self.question.config = {'min': 1, 'max': 5, 'chart_weight': 2.0, 'exclude_from_charts': True}
        self.question.save()

        self.edit(question_type='rating', question_text='How well does this person solve problems?')

        self.assertEqual(self.question.config, {'min': 1, 'max': 5, 'chart_weight': 2.0, 'exclude_from_charts': True})

    def likert_fields(self, **fields):
        return {
            'question_type': 'likert', 'question_text': 'This person often misses deadlines',
            'likert_option_id': ['', ''], 'likert_option_label': ['Never', 'Often'], **fields,
        }

    def test_a_likert_question_is_reverse_scored_while_the_box_is_checked(self):
        self.edit(**self.likert_fields(reverse_scored='on'))
        self.assertEqual(self.question.config, {'reverse_scored': True, 'dreyfus_mapping': {'skill': 1.5}})

        # The dialog posts the box again on every later edit
        self.edit(**self.likert_fields(reverse_scored='on', question_text='This person misses deadlines'))
        self.assertIs(self.question.config['reverse_scored'], True)

        self.edit(**self.likert_fields())
        self.assertNotIn('reverse_scored', self.question.config)

    def test_a_new_likert_question_can_be_reverse_scored(self):
        self.client.post(reverse('questionnaire_edit', args=[self.questionnaire.uuid]), {
            'action': 'add_question', 'section_id': self.question.section_id, **self.likert_fields(reverse_scored='on'),
        })

        added = Question.objects.get(question_text='This person often misses deadlines')
        self.assertEqual(added.config, {'reverse_scored': True})

    def test_only_a_likert_question_is_reverse_scored(self):
        self.edit(question_type='rating', question_text=self.question.question_text, reverse_scored='on')

        self.assertNotIn('reverse_scored', self.question.config)
