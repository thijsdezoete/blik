from django.test import TestCase

from questionnaires.factories import (
    LikertQuestionFactory,
    QuestionnaireFactory,
    QuestionFactory,
    QuestionSectionFactory,
    TextQuestionFactory,
)
from questionnaires.models import AnswerOption, Questionnaire
from questionnaires.presentation import questionnaire_report_features


class QuestionnaireReportFeaturesTests(TestCase):
    def setUp(self):
        self.questionnaire = QuestionnaireFactory()
        self.section = QuestionSectionFactory(questionnaire=self.questionnaire)

    def feature_keys(self, questionnaire=None):
        return [
            feature['key']
            for feature in questionnaire_report_features(questionnaire or self.questionnaire)
        ]

    def add_choice(self, question_type='single_choice', weights=(1, 5), **config):
        question = QuestionFactory(
            section=self.section,
            question_type=question_type,
            config=config,
        )
        for order, weight in enumerate(weights):
            AnswerOption.objects.create(
                question=question, order=order, label=f'Option {order}', weight=weight
            )
        return question

    def test_empty_questionnaire_has_no_report_features(self):
        self.assertEqual(self.feature_keys(), [])

    def test_text_only_questionnaire_supports_written_feedback(self):
        TextQuestionFactory(section=self.section)
        self.assertEqual(self.feature_keys(), ['written'])

    def test_rating_and_numeric_scale_support_radar(self):
        for question_type, expected in (
            ('rating', ['radar', 'distribution']),
            ('scale', ['radar']),
        ):
            with self.subTest(question_type=question_type):
                question = QuestionFactory(section=self.section, question_type=question_type)
                try:
                    self.assertEqual(self.feature_keys(), expected)
                finally:
                    question.delete()

    def test_likert_supports_radar_skill_and_initiative(self):
        LikertQuestionFactory(
            section=self.section, config={'dreyfus_mapping': {'skill': 1, 'agency': 1}}
        )
        self.assertEqual(self.feature_keys(), ['radar', 'dreyfus', 'agency', 'distribution'])

    def test_likert_with_one_option_has_no_score(self):
        LikertQuestionFactory(
            section=self.section, answer_options=['Agree'], config={'dreyfus_mapping': {'skill': 1}}
        )
        self.assertEqual(self.feature_keys(), ['distribution'])

    def test_likert_without_options_cannot_offer_answer_breakdown(self):
        QuestionFactory(section=self.section, question_type='likert', config={})
        self.assertEqual(self.feature_keys(), [])

    def test_choice_visuals_require_scoring_and_weighted_options(self):
        for question_type in ('single_choice', 'multiple_choice'):
            for scoring_enabled, weights, expected in (
                (False, (1, 5), ['distribution']),
                (True, (), []),
                (True, (None, None), ['distribution']),
                (True, (None, 0), ['radar', 'distribution']),
                (True, (1, 5), ['radar', 'distribution']),
            ):
                with self.subTest(
                    question_type=question_type, scoring_enabled=scoring_enabled, weights=weights
                ):
                    question = self.add_choice(
                        question_type, weights, scoring_enabled=scoring_enabled
                    )
                    try:
                        self.assertEqual(self.feature_keys(), expected)
                    finally:
                        question.delete()

    def test_scored_choice_can_support_skill_and_initiative(self):
        self.add_choice(scoring_enabled=True, dreyfus_mapping={'skill': 1, 'agency': 0.5})
        self.assertEqual(self.feature_keys(), ['radar', 'dreyfus', 'agency', 'distribution'])

    def test_zero_only_choice_scores_cannot_produce_skill_profile(self):
        self.add_choice(
            weights=(0,), scoring_enabled=True, dreyfus_mapping={'skill': 1, 'agency': 1}
        )
        self.assertEqual(self.feature_keys(), ['radar', 'distribution'])

    def test_excluding_radar_does_not_exclude_skill_profiles(self):
        QuestionFactory(
            section=self.section,
            config={'exclude_from_charts': True, 'dreyfus_mapping': {'skill': 1, 'agency': 1}},
        )
        self.assertEqual(self.feature_keys(), ['dreyfus', 'agency', 'distribution'])

    def test_excluded_unscored_choices_still_offer_answer_breakdown(self):
        for question_type in ('single_choice', 'multiple_choice'):
            with self.subTest(question_type=question_type):
                question = self.add_choice(
                    question_type, weights=(None, None), exclude_from_charts=True
                )
                try:
                    self.assertEqual(self.feature_keys(), ['distribution'])
                finally:
                    question.delete()

    def test_radar_requires_a_positive_chart_weight(self):
        for weight, expected in (
            (0, ['distribution']),
            (-1, ['distribution']),
            (0.5, ['radar', 'distribution']),
            (None, ['distribution']),
            ('bad', ['distribution']),
        ):
            with self.subTest(weight=weight):
                question = QuestionFactory(section=self.section, config={'chart_weight': weight})
                try:
                    self.assertEqual(self.feature_keys(), expected)
                finally:
                    question.delete()

    def test_initiative_shows_without_skill_level(self):
        QuestionFactory(section=self.section, config={'dreyfus_mapping': {'agency': 1}})
        self.assertIn('agency', self.feature_keys())
        self.assertNotIn('dreyfus', self.feature_keys())

    def test_dimensions_on_separate_questions_enable_both_profiles(self):
        QuestionFactory(section=self.section, config={'dreyfus_mapping': {'skill': 1}})
        QuestionFactory(section=self.section, config={'dreyfus_mapping': {'agency': 0.5}})
        self.assertEqual(self.feature_keys(), ['radar', 'dreyfus', 'agency', 'distribution'])

    def test_legacy_mapping_is_supported(self):
        QuestionFactory(
            section=self.section, config={'dreyfus_mapping': {'dimension': 'skill'}}
        )
        QuestionFactory(
            section=self.section,
            config={'dreyfus_mapping': {'dimension': 'agency', 'weight': 0.5}},
        )
        self.assertEqual(self.feature_keys(), ['radar', 'dreyfus', 'agency', 'distribution'])

    def test_new_zero_weight_takes_precedence_over_legacy_mapping(self):
        QuestionFactory(
            section=self.section,
            config={'dreyfus_mapping': {'skill': 0, 'dimension': 'skill', 'weight': 1}},
        )
        self.assertEqual(self.feature_keys(), ['radar', 'distribution'])

    def test_numeric_string_mapping_weights_are_not_supported_by_reports(self):
        QuestionFactory(
            section=self.section, config={'dreyfus_mapping': {'skill': '1.5', 'agency': '0.5'}}
        )
        self.assertEqual(self.feature_keys(), ['radar', 'distribution'])

    def test_mapping_on_text_question_cannot_produce_a_skill_profile(self):
        TextQuestionFactory(
            section=self.section, config={'dreyfus_mapping': {'skill': 1, 'agency': 1}}
        )
        self.assertEqual(self.feature_keys(), ['written'])

    def test_malformed_config_does_not_break_overview(self):
        for config in ([], 'bad', {'dreyfus_mapping': 'bad'}, {'dreyfus_mapping': {'skill': 'bad'}}):
            with self.subTest(config=config):
                question = QuestionFactory(section=self.section, config=config)
                expected = ['radar', 'distribution'] if isinstance(config, dict) else []
                try:
                    self.assertEqual(self.feature_keys(), expected)
                finally:
                    question.delete()

    def test_legacy_section_title_does_not_imply_skill_profile_for_current_reports(self):
        self.section.title = 'Technical Expertise & Skill Level'
        self.section.save()
        QuestionFactory(section=self.section)
        self.assertEqual(self.feature_keys(), ['radar', 'distribution'])

    def test_all_features_are_ordered_and_deduplicated_without_queries_after_prefetch(self):
        QuestionFactory(section=self.section, config={'dreyfus_mapping': {'skill': 1}})
        self.add_choice(scoring_enabled=True, dreyfus_mapping={'skill': 1, 'agency': 1})
        TextQuestionFactory(section=self.section)
        TextQuestionFactory(section=self.section)
        questionnaire = Questionnaire.objects.prefetch_related(
            *Questionnaire.translation_lookups()
        ).get(pk=self.questionnaire.pk)

        with self.assertNumQueries(0):
            features = questionnaire_report_features(questionnaire)

        self.assertEqual(
            [feature['key'] for feature in features],
            ['radar', 'dreyfus', 'agency', 'distribution', 'written'],
        )
        for feature in features:
            self.assertTrue(str(feature['label']))
            self.assertTrue(str(feature['description']))
