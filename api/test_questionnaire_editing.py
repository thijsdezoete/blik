"""The API changes the order of a questionnaire and the descriptions of its rating questions, nothing else."""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from api.models import APIToken
from core.models import Organization
from questionnaires.models import Question, QuestionSection, Questionnaire


class QuestionnaireEditingTest(TestCase):

    def setUp(self):
        ensure_permission_groups()
        self.organization = Organization.objects.create(name='Org', email='org@example.com')
        self.admin = self.create_user('admin', admin=True)
        self.questionnaire = Questionnaire.objects.create(name='Q', organization=self.organization)
        self.first = QuestionSection.objects.create(questionnaire=self.questionnaire, title='First', order=0)
        self.second = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Second', order=1)
        self.rating = Question.objects.create(section=self.first, question_text='A', question_type='rating', order=0)
        self.text = Question.objects.create(section=self.second, question_text='B', question_type='text', order=0)
        self.client = self.client_for(self.admin)

    def create_user(self, name, admin=False):
        user = User.objects.create_user(name, f'{name}@example.com', 'pw')
        UserProfile.objects.create(user=user, organization=self.organization)

        if admin:
            assign_organization_admin(user)

        return user

    def client_for(self, user):
        token = APIToken.objects.create(organization=self.organization, created_by=user, name=user.username)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.raw_token}')

        return client

    def reorder(self, sections, client=None, questionnaire=None):
        return (client or self.client).post(
            f'/api/v1/questionnaires/{(questionnaire or self.questionnaire).uuid}/reorder/',
            {'sections': sections},
            format='json',
        )

    def patch_question(self, question, data):
        return self.client.patch(
            f'/api/v1/questionnaires/{self.questionnaire.uuid}/questions/{question.uuid}/', data, format='json'
        )

    def layout(self):
        return [
            (section.title, [question.question_text for question in section.questions.all()])
            for section in self.questionnaire.sections.all()
        ]

    def test_reorder_swaps_sections_and_moves_a_question(self):
        response = self.reorder([
            {'uuid': f'{self.second.uuid}', 'questions': [f'{self.text.uuid}', f'{self.rating.uuid}']},
            {'uuid': f'{self.first.uuid}', 'questions': []},
        ])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.layout(), [('Second', ['B', 'A']), ('First', [])])
        self.assertEqual(response.data['sections'][0]['uuid'], self.second.uuid)

    def test_reorder_refuses_an_incomplete_or_malformed_layout(self):
        for sections in [
            [{'uuid': f'{self.first.uuid}', 'questions': [f'{self.rating.uuid}']}],
            [{'uuid': 'not-a-uuid', 'questions': []}],
            'everything',
        ]:
            with self.subTest(sections=sections):
                self.assertEqual(self.reorder(sections).status_code, 400)

        self.assertEqual(self.layout(), [('First', ['A']), ('Second', ['B'])])

    def test_shared_templates_cannot_be_reordered(self):
        template = Questionnaire.objects.create(name='Template', organization=None)

        self.assertEqual(self.reorder([], questionnaire=template).status_code, 404)

    def test_changing_takes_the_permission_to_manage_questionnaires(self):
        client = self.client_for(self.create_user('member'))

        self.assertEqual(self.reorder([], client=client).status_code, 403)

    def test_descriptions_are_stored_without_the_empty_ones(self):
        response = self.patch_question(self.rating, {'descriptions': {'1': ' Almost never on time ', '2': ''}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['descriptions'], {'1': 'Almost never on time'})
        self.rating.refresh_from_db()
        self.assertEqual(self.rating.descriptions, {'1': 'Almost never on time'})

    def test_descriptions_are_refused_for_unknown_values_and_other_question_types(self):
        self.assertEqual(self.patch_question(self.rating, {'descriptions': {'6': 'Beyond'}}).status_code, 400)
        self.assertEqual(self.patch_question(self.text, {'descriptions': {'1': 'Late'}}).status_code, 400)
