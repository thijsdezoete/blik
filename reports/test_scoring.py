"""The average of any scored question comes to the 1 to 5 scale of the reports and charts."""
from django.test import SimpleTestCase, TestCase

from accounts.models import Reviewee
from core.models import Organization
from questionnaires.answer_options import save_options
from questionnaires.models import Question, Questionnaire, QuestionSection
from reviews.models import ReviewCycle, ReviewerToken, Response

from .scoring import score_on_five, score_range
from .services import generate_report


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

    def test_a_range_that_is_not_a_number_stays_as_it_is(self):
        self.assertEqual(score_on_five(q('rating', {'min': 1, 'max': '4'}), 3), 3)
        self.assertEqual(score_on_five(q('scale', {'min': 'low', 'max': 10}), 7), 7)
        self.assertEqual(score_on_five(q('scale', {'min': [1], 'max': 10}), 7), 7)
        self.assertEqual(score_on_five(q('rating', {'min': False, 'max': True}), 1), 1)

    def test_a_score_whose_number_of_options_is_broken_counts_as_five_options(self):
        for highest in ('4', 8, 4.0, True):
            with self.subTest(max=highest):
                self.assertEqual(score_on_five(q('rating', {'min': 1, 'max': highest}), 3.2), 3.2)


class ReportScaleTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='Acme', email='org@acme.example', min_responses_for_anonymity=3,
        )
        self.questionnaire = Questionnaire.objects.create(name='Teamwork', organization=self.organization)
        reviewee = Reviewee.objects.create(name='Dana', email='dana@acme.example', organization=self.organization)
        self.cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=self.questionnaire)
        self.tokens = [ReviewerToken.objects.create(cycle=self.cycle, category='peer') for _i in range(3)]

    def add_question(self, question_type, config, section_title='Collaboration', weights=(), **fields):
        section, _created = QuestionSection.objects.get_or_create(
            questionnaire=self.questionnaire, title=section_title,
            defaults={'order': self.questionnaire.sections.count()},
        )
        question = Question.objects.create(
            section=section, question_text='Shares what they know', question_type=question_type, config=config,
            order=section.questions.count(), **fields,
        )
        if weights:
            save_options(question, [(None, f'Option {weight}', weight) for weight in weights])
        return question

    def answer(self, question, values):
        """One peer answer per value, each from its own token."""
        for token, value in zip(self.tokens, values):
            Response.objects.create(
                cycle=self.cycle, question=question, token=token, category='peer', answer_data={'value': value},
            )

    def report_data(self):
        return generate_report(self.cycle, notify=False).report_data

    def test_a_slider_counts_toward_skill_on_the_1_to_5_scale(self):
        question = self.add_question('scale', {'min': 1, 'max': 10, 'dreyfus_mapping': {'skill': 1}})
        self.answer(question, [7, 8, 8])

        data = self.report_data()

        self.assertEqual(data['insights']['skill_profile']['skill_level'], 3.96)  # 1 + 6.67 / 9 * 4

    def test_an_average_of_zero_counts_toward_the_level(self):
        question = self.add_question('scale', {'min': 0, 'max': 10, 'dreyfus_mapping': {'skill': 1}})
        self.answer(question, [0, 0, 0])

        data = self.report_data()

        self.assertEqual(data['insights']['skill_profile']['skill_level'], 1.0)

    def test_a_pick_question_whose_every_score_is_0_counts_toward_no_level(self):
        # As the editor's preview says (Scoring.nonzero): such a question has no range on the 1 to 5 scale
        question = self.add_question('single_choice', {'scoring_enabled': True, 'dreyfus_mapping': {'skill': 1}},
                                     weights=(0, 0))
        self.answer(question, [question.options.first().id] * 3)

        self.assertIsNone(self.report_data()['insights']['skill_profile'])

        other = self.add_question('rating', {'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1}})
        self.answer(other, [5, 5, 5])

        self.assertEqual(self.report_data()['insights']['skill_profile']['skill_level'], 5.0)

    def test_pick_several_cannot_score_above_5_in_the_charts(self):
        question = self.add_question('multiple_choice', {'scoring_enabled': True}, weights=(1, 2, 3))
        all_options = [option.id for option in question.options.all()]
        self.answer(question, [all_options] * 3)

        data = self.report_data()

        self.assertEqual(data['charts']['section_scores']['Collaboration']['peer'], 5.0)

    def test_a_four_point_score_gives_an_overall_score_out_of_5(self):
        question = self.add_question('rating', {'min': 1, 'max': 4})
        self.answer(question, [4, 4, 4])

        data = self.report_data()

        self.assertEqual(data['insights']['overall_sentiment']['score'], 5.0)

    def test_advice_compares_the_score_on_the_1_to_5_scale(self):
        question = self.add_question(
            'scale', {'min': 1, 'max': 10, 'dreyfus_mapping': {'skill': 1}},
            action_items=[{'key': 'a', 'text': 'Practise', 'threshold': 3.0}],
        )
        # 5 is 2.78 on the 1 to 5 scale, below the threshold
        self.answer(question, [5, 5, 5])

        data = self.report_data()

        self.assertEqual([item['key'] for item in data['insights']['development_plan']['action_items']], ['a'])

    def test_no_question_counts_means_no_skill_level(self):
        question = self.add_question('rating', {}, section_title='Technical Expertise & Skill Level')
        self.answer(question, [4, 4, 5])

        data = self.report_data()

        self.assertIsNone(data['insights']['skill_profile'])
