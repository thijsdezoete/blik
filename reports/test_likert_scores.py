"""Likert answers score by the position of their option and count in the scores and charts of a report."""
from django.test import SimpleTestCase, TestCase

from accounts.models import Reviewee
from core.models import Organization
from questionnaires.answer_options import save_options
from questionnaires.models import Question, Questionnaire, QuestionSection
from reviews.models import ReviewCycle, ReviewerToken, Response
from reviews.templatetags.feedback_tags import likert_positive_count

from .services import apply_display_anonymization, generate_report, likert_score, radar_axes


def options(count):
    return [{'id': option_id} for option_id in range(11, 11 + count)]


class LikertScoreTests(SimpleTestCase):
    def scores(self, count, **kwargs):
        return [likert_score(options(count), option['id'], **kwargs) for option in options(count)]

    def test_the_first_option_scores_1_and_the_last_5_on_a_scale_of_any_length(self):
        self.assertEqual(self.scores(3), [1, 3, 5])
        self.assertEqual(self.scores(4), [1, 1 + 4 / 3, 1 + 8 / 3, 5])
        self.assertEqual(self.scores(5), [1, 2, 3, 4, 5])
        self.assertEqual(self.scores(7), [1, 1 + 4 / 6, 1 + 8 / 6, 3, 1 + 16 / 6, 1 + 20 / 6, 5])

    def test_a_reverse_scored_question_counts_from_the_other_end(self):
        for count in (3, 4, 5, 7):
            with self.subTest(count=count):
                self.assertEqual(self.scores(count, reverse_scored=True), self.scores(count)[::-1])

    def test_an_option_id_stored_as_text_scores_like_the_number(self):
        self.assertEqual(likert_score(options(5), '14'), 4)

    def test_an_answer_that_names_no_option_has_no_score(self):
        # 2 is a position on the scale, not the id of an option: it must not score as one
        for answer in (2, 99, 'Agree', None):
            with self.subTest(answer=answer):
                self.assertIsNone(likert_score(options(5), answer))

    def test_a_scale_of_one_option_has_no_score(self):
        self.assertIsNone(likert_score(options(1), 11))
        self.assertIsNone(likert_score([], 11))


class LikertReportTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='Acme', email='org@acme.example', min_responses_for_anonymity=3,
        )
        self.questionnaire = Questionnaire.objects.create(name='Teamwork', organization=self.organization)
        reviewee = Reviewee.objects.create(name='Dana', email='dana@acme.example', organization=self.organization)
        self.cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=self.questionnaire)
        self.question = self.add_question('Collaboration', 'Shares what they know')

    def add_question(self, section_title, text, labels=('Never', 'Sometimes', 'Often', 'Always'), **config):
        section, _created = QuestionSection.objects.get_or_create(
            questionnaire=self.questionnaire, title=section_title,
            defaults={'order': self.questionnaire.sections.count()},
        )
        question = Question.objects.create(
            section=section, question_text=text, question_type='likert', config=config,
            order=section.questions.count(),
        )
        save_options(question, [(None, label, None) for label in labels])
        return question

    def answer(self, category, position, question=None):
        """An answer that picks the option at the 1-based position, stored as the option's id."""
        question = question or self.question
        token = ReviewerToken.objects.create(cycle=self.cycle, category=category)
        Response.objects.create(
            cycle=self.cycle, question=question, token=token, category=category,
            answer_data={'value': list(question.options.all())[position - 1].id},
        )

    def category_data(self, report, category, question=None):
        question = question or self.question
        section = report.report_data['by_section'][str(question.section_id)]
        return section['questions'][str(question.id)]['by_category'][category]

    def test_a_likert_only_questionnaire_has_section_scores(self):
        for position in (3, 4, 4):
            self.answer('peer', position)
        self.answer('self', 2)

        report = generate_report(self.cycle)

        # Four options: Often is 1 + 2/3 * 4, Always is 5, Sometimes is 1 + 1/3 * 4
        self.assertEqual(self.category_data(report, 'peer')['avg'], 4.56)
        self.assertEqual(report.report_data['charts']['section_scores'], {
            'Collaboration': {'self': 2.33, 'peer': 4.56, 'others_avg': 4.56},
        })
        self.assertEqual(report.report_data['section_summary'], {'Collaboration': {'self': 2.33, 'peer': 4.56}})
        self.assertEqual(report.report_data['insights']['overall_sentiment']['score'], 4.56)
        self.assertEqual(self.category_data(report, 'peer')['distribution'], {
            f'{option.id}': count for option, count in zip(self.question.options.all(), [0, 0, 1, 2]) if count
        })

    def test_a_reverse_scored_question_scores_its_first_option_highest(self):
        question = self.add_question('Reliability', 'Misses deadlines', reverse_scored=True)
        for position in (1, 1, 2):
            self.answer('peer', position, question)

        report = generate_report(self.cycle)

        self.assertEqual(self.category_data(report, 'peer', question)['avg'], 4.56)
        self.assertEqual(report.report_data['charts']['section_scores']['Reliability']['peer'], 4.56)

    def test_one_peer_is_too_few_for_a_score_as_for_a_rating(self):
        self.answer('peer', 4)
        self.answer('manager', 3)

        report = generate_report(self.cycle)

        self.assertEqual(report.report_data['charts']['section_scores'], {
            'Collaboration': {'manager': 3.67, 'others_avg': 3.67},
        })
        self.assertEqual(report.report_data['section_summary'], {'Collaboration': {'manager': 3.67}})

    def test_an_answer_without_its_option_is_left_out_of_the_score(self):
        for position in (4, 4, 1):
            self.answer('peer', position)
        # The first option is deleted after the answers were given: 'Sometimes' becomes the lowest of three
        save_options(self.question, [(option.id, option.label, None) for option in self.question.options.all()[1:]])

        report = generate_report(self.cycle)

        self.assertEqual(self.category_data(report, 'peer')['count'], 3)
        self.assertEqual(self.category_data(report, 'peer')['avg'], 5.0)

    def test_a_group_below_the_anonymity_threshold_is_left_out_of_the_shown_charts(self):
        for position in (4, 4):
            self.answer('peer', position)
        self.answer('manager', 2)
        report = generate_report(self.cycle)
        self.assertEqual(report.report_data['charts']['section_scores']['Collaboration']['peer'], 5.0)

        shown = apply_display_anonymization(report.report_data, min_threshold=3)

        self.assertEqual(shown['charts']['section_scores'], {'Collaboration': {'manager': 2.33, 'others_avg': 2.33}})
        self.assertEqual(shown['insights']['overall_sentiment']['score'], 2.33)
        self.assertNotIn('distribution', self.category_data_of(shown, 'peer'))

    def category_data_of(self, report_data, category):
        section = report_data['by_section'][str(self.question.section_id)]
        return section['questions'][str(self.question.id)]['by_category'][category]

    def test_a_mapped_likert_question_counts_in_the_skill_level(self):
        question = self.add_question('Craft', 'Writes clear code', dreyfus_mapping={'skill': 1.0})
        for position in (3, 4):
            self.answer('peer', position, question)

        report = generate_report(self.cycle)

        self.assertEqual(report.report_data['insights']['skill_profile']['skill_level'], 4.33)


class LikertPositiveCountTests(SimpleTestCase):
    def question(self, **config):
        return {'options': [{'id': 1}, {'id': 2}, {'id': 3}, {'id': 4}, {'id': 5}], 'question_config': config}

    def test_the_two_highest_options_are_positive(self):
        distribution = {'1': 3, '2': 2, '4': 1, '5': 1}

        self.assertEqual(likert_positive_count(distribution, self.question()), 2)

    def test_the_two_lowest_options_are_positive_when_the_question_is_reverse_scored(self):
        distribution = {'1': 3, '2': 2, '4': 1, '5': 1}

        self.assertEqual(likert_positive_count(distribution, self.question(reverse_scored=True)), 5)


class RadarAxesTests(SimpleTestCase):
    def test_three_sections_are_the_axes(self):
        scores = {'Collaboration': {'peer': 4.0}, 'Reliability': {'peer': 3.0}, 'Craft': {'peer': 5.0}}

        self.assertEqual(radar_axes(scores), scores)

    def test_two_sections_get_an_overall_axis_with_the_mean_of_each_group(self):
        scores = {
            'Collaboration': {'self': 3.0, 'peer': 4.0, 'manager': 5.0, 'others_avg': 4.5},
            'Reliability': {'self': 4.0, 'peer': 3.5, 'others_avg': 3.5},
        }

        axes = radar_axes(scores)

        self.assertEqual(list(axes), ['Collaboration', 'Reliability', 'Overall'])
        # The manager scored one section, and the others' average is no reviewer group
        self.assertEqual(axes['Overall'], {'self': 3.5, 'peer': 3.75, 'manager': 5.0})
        self.assertEqual(list(scores), ['Collaboration', 'Reliability'])

    def test_a_group_hidden_for_anonymity_gets_no_overall_score(self):
        hidden = {'insufficient': True}

        axes = radar_axes({'Collaboration': {'peer': hidden, 'manager': 4.0}, 'Reliability': {'manager': 3.0}})

        self.assertEqual(axes['Overall'], {'manager': 3.5})

    def test_one_section_or_none_makes_no_radar(self):
        self.assertIsNone(radar_axes({'Collaboration': {'peer': 4.0}}))
        self.assertIsNone(radar_axes({}))

    def test_two_sections_of_which_one_is_titled_overall_make_no_radar(self):
        self.assertIsNone(radar_axes({'Collaboration': {'peer': 4.0}, 'Overall': {'peer': 3.0}}))
