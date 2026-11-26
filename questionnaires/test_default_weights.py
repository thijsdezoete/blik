"""The command that removes the skill and initiative weights the old editor gave every new question."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import Organization
from questionnaires.models import Question, Questionnaire, QuestionSection

DEFAULT = {'skill': 1.0, 'agency': 1.0}


class ClearDefaultWeightsTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Acme', email='org@acme.example')

    def questionnaire(self, name, mappings, **fields):
        fields.setdefault('organization', self.organization)
        questionnaire = Questionnaire.objects.create(name=name, **fields)
        section = QuestionSection.objects.create(questionnaire=questionnaire, title='Communication')

        for order, mapping in enumerate(mappings):
            config = {'min': 1, 'max': 5}

            if mapping is not None:
                config['dreyfus_mapping'] = mapping

            Question.objects.create(
                section=section, question_text=f'Question {order}', question_type='rating', config=config, order=order,
            )

        return questionnaire

    def mappings(self, questionnaire):
        questions = Question.objects.filter(section__questionnaire=questionnaire).order_by('order')

        return [question.config.get('dreyfus_mapping') for question in questions]

    def run_command(self, *args):
        out = StringIO()
        call_command('clear_default_model_weights', *args, stdout=out)

        return out.getvalue()

    def test_without_apply_it_lists_and_changes_nothing(self):
        affected = self.questionnaire('Team check', [DEFAULT, DEFAULT, None])

        output = self.run_command()

        self.assertIn('Team check', output)
        self.assertIn('Acme', output)
        self.assertIn('2 of 3 questions', output)
        self.assertEqual(self.mappings(affected), [DEFAULT, DEFAULT, None])

    def test_apply_removes_the_default_weights_and_keeps_the_rest_of_the_config(self):
        affected = self.questionnaire('Team check', [DEFAULT, {'skill': 1, 'agency': 1}, None])

        self.run_command('--apply')

        self.assertEqual(self.mappings(affected), [None, None, None])
        question = Question.objects.filter(section__questionnaire=affected).first()
        self.assertEqual(question.config, {'min': 1, 'max': 5})

    def test_a_questionnaire_with_a_chosen_weight_is_left_alone(self):
        # One weight that is not the default shows that somebody set the weights on purpose
        chosen = self.questionnaire('Growth check', [DEFAULT, {'skill': 1.5}, {'skill': 1.0}])

        output = self.run_command('--apply')

        self.assertEqual(self.mappings(chosen), [DEFAULT, {'skill': 1.5}, {'skill': 1.0}])
        self.assertIn('Growth check', output)
        self.assertIn('left alone', output)

    def test_templates_and_questionnaires_made_from_a_shipped_template_are_left_alone(self):
        template = self.questionnaire('Shipped', [DEFAULT], organization=None)
        from_template = self.questionnaire('From a template', [DEFAULT], template_key='simple')

        output = self.run_command('--apply')

        self.assertEqual(self.mappings(template), [DEFAULT])
        self.assertEqual(self.mappings(from_template), [DEFAULT])
        self.assertNotIn('Shipped', output)
        self.assertNotIn('From a template', output)

    def test_apply_can_be_limited_to_chosen_questionnaires(self):
        first = self.questionnaire('First', [DEFAULT])
        second = self.questionnaire('Second', [DEFAULT])

        self.run_command('--apply', '--questionnaire', f'{first.id}')

        self.assertEqual(self.mappings(first), [None])
        self.assertEqual(self.mappings(second), [DEFAULT])

    def test_a_questionnaire_without_weights_is_not_listed(self):
        self.questionnaire('Plain', [None, None])

        output = self.run_command()

        self.assertNotIn('Plain', output)
        self.assertIn('No questionnaire', output)
