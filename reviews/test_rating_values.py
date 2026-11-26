from django.test import SimpleTestCase

from questionnaires.models import Question
from reviews.templatetags.feedback_tags import rating_values


class RatingValuesTests(SimpleTestCase):
    def test_a_score_has_as_many_values_as_its_config_says(self):
        self.assertEqual(rating_values(Question(config={'min': 1, 'max': 4})), ['1', '2', '3', '4'])
        self.assertEqual(rating_values({'question_config': {'max': 7}}), ['1', '2', '3', '4', '5', '6', '7'])

    def test_a_broken_number_of_options_gives_five(self):
        five = ['1', '2', '3', '4', '5']
        for config in ({}, None, {'max': 'many'}, {'max': 1}, {'max': 8}, {'max': None}):
            self.assertEqual(rating_values(Question(config=config)), five)
            self.assertEqual(rating_values({'question_config': config}), five)
