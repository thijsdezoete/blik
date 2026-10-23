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
            config={'min': 1, 'max': 5, 'labels': LABELS, 'dreyfus_mapping': {'skill': 1.5}},
        )

    def edit(self, **fields):
        self.client.post(reverse('questionnaire_edit', args=[self.questionnaire.id]), {
            'action': 'edit_question', 'question_id': self.question.id, 'required': 'on', **fields,
        })
        self.question.refresh_from_db()

    def test_fixing_the_text_keeps_the_labels_and_the_dreyfus_weights(self):
        self.edit(question_type='rating', question_text='How well does this person solve problems?')

        self.assertEqual(self.question.question_text, 'How well does this person solve problems?')
        self.assertEqual(self.question.config['labels'], LABELS)
        self.assertEqual(self.question.config['dreyfus_mapping'], {'skill': 1.5})

    def test_another_type_drops_the_rating_labels_but_keeps_the_dreyfus_weights(self):
        self.edit(question_type='likert', question_text=self.question.question_text, likert_scale='Never\nOften')

        self.assertEqual(self.question.config['scale'], ['Never', 'Often'])
        self.assertNotIn('labels', self.question.config)
        self.assertEqual(self.question.config['dreyfus_mapping'], {'skill': 1.5})
