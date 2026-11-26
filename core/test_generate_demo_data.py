from django.test import SimpleTestCase

from core.management.commands.generate_demo_data import Command
from questionnaires.models import Question


class GeneratedRatingTests(SimpleTestCase):

    def test_a_rating_never_exceeds_the_highest_value_of_the_question(self):
        question = Question(question_type='rating', config={'min': 1, 'max': 3})
        command = Command()
        patterns = ['high_performer', 'solid_performer', 'developing', 'imposter_syndrome', 'overconfident']

        values = [
            command._generate_answer(question, 'peer', patterns[i % len(patterns)])['value'] for i in range(200)
        ]

        self.assertTrue(all(1 <= value <= 3 for value in values), sorted(set(values)))
