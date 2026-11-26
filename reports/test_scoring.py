"""The average of any scored question comes to the 1 to 5 scale of the reports and charts."""
from django.test import SimpleTestCase

from .scoring import score_on_five, score_range


def q(question_type, config=None, weights=()):
    options = [{'id': i, 'label': f'{i}', 'weight': w} for i, w in enumerate(weights, 1)]
    return {'question_type': question_type, 'question_config': config, 'options': options}


class ScoreOnFiveTests(SimpleTestCase):
    def test_a_score_counts_by_its_number_of_options(self):
        self.assertEqual(score_on_five(q('rating', {'min': 1, 'max': 4}), 4), 5)
        self.assertEqual(score_on_five(q('rating', {'min': 1, 'max': 4}), 1), 1)
        self.assertEqual(score_on_five(q('rating', {'min': 1, 'max': 4}), 2.5), 3)
        self.assertEqual(score_on_five(q('rating', {'min': 1, 'max': 2}), 2), 5)

    def test_a_five_point_score_and_a_likert_stay_as_they_are(self):
        for data in (q('rating', {'min': 1, 'max': 5}), q('rating', {}), q('rating', None), q('likert', {})):
            self.assertEqual(score_on_five(data, 3.2), 3.2)

    def test_a_slider_counts_by_its_lowest_and_highest_number(self):
        self.assertAlmostEqual(score_on_five(q('scale', {'min': 1, 'max': 10}), 7.3), 3.8)
        self.assertEqual(score_on_five(q('scale', {}), 100), 5)  # defaults 1 and 100
        self.assertEqual(score_on_five(q('scale', {'min': 3, 'max': 3}), 3), 3)  # no range: unchanged

    def test_pick_one_counts_by_its_lowest_and_highest_score(self):
        data = q('single_choice', {'scoring_enabled': True}, [0, 1, 3, None])
        self.assertEqual(score_range(data), (0, 3))
        self.assertEqual(score_on_five(data, 3), 5)
        self.assertAlmostEqual(score_on_five(data, 1), 1 + 4 / 3)

    def test_pick_several_counts_by_the_lowest_and_highest_sum(self):
        self.assertEqual(score_range(q('multiple_choice', {'scoring_enabled': True}, [1, 2, 3])), (1, 6))
        self.assertEqual(score_on_five(q('multiple_choice', {'scoring_enabled': True}, [1, 2, 3]), 6), 5)
        self.assertEqual(score_range(q('multiple_choice', {'scoring_enabled': True}, [-1, 2, 3])), (-1, 5))
        self.assertEqual(score_range(q('multiple_choice', {'scoring_enabled': True}, [-1, -2])), (-3, -1))

    def test_a_question_without_a_range_stays_as_it_is(self):
        self.assertIsNone(score_range(q('single_choice', {'scoring_enabled': True}, [None])))
        self.assertEqual(score_on_five(q('single_choice', {'scoring_enabled': True}, []), 2), 2)
        self.assertEqual(score_on_five(q('text', {}), 2), 2)
