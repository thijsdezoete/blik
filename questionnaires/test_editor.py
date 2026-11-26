from django.http import QueryDict
from django.test import SimpleTestCase, TestCase

from core.models import Organization
from questionnaires.editor import (
    EditorError,
    clear_model,
    did_not_observe_state,
    example_score,
    rating_labels,
    report_preview,
    save_question,
    set_did_not_observe,
    set_weight,
)
from questionnaires.models import AnswerOption, Question, QuestionSection, QuestionTranslation, Questionnaire
from reviews.factories import ResponseFactory, ReviewCycleFactory, ReviewerTokenFactory

D = {'1': 'Strongly Disagree', '2': 'Disagree', '3': 'Neutral', '4': 'Agree', '5': 'Strongly Agree'}


def post(**fields):
    """The fields as the editor posts them; a list posts one value per item."""

    data = QueryDict(mutable=True)

    for name, value in fields.items():
        data.setlist(name, value if isinstance(value, list) else [value])

    return data


class RatingLabelsTests(SimpleTestCase):
    def test_the_same_number_takes_what_was_typed(self):
        posted = {'1': 'Never', '5': 'Always', '3': ''}
        self.assertEqual(rating_labels(D, 5, posted, 5, D), {'1': 'Never', '5': 'Always'})

    def test_default_labels_keep_only_their_ends_on_another_number(self):
        self.assertEqual(rating_labels(D, 5, D, 4, D), {'1': 'Strongly Disagree', '4': 'Strongly Agree'})

    def test_the_ends_move_with_the_number_and_five_gets_the_full_default_back(self):
        ends = {'1': 'Strongly Disagree', '4': 'Strongly Agree'}
        self.assertEqual(rating_labels(ends, 4, ends, 7, D), {'1': 'Strongly Disagree', '7': 'Strongly Agree'})
        self.assertEqual(rating_labels(ends, 4, ends, 5, D), D)

    def test_typed_labels_are_never_overwritten(self):
        typed = {'1': 'Never', '2': 'Rarely', '3': 'Often', '4': 'Mostly', '5': 'Always'}
        self.assertEqual(rating_labels(typed, 5, typed, 3, D), {'1': 'Never', '2': 'Rarely', '3': 'Often'})
        self.assertEqual(rating_labels(typed, 5, typed, 6, D), typed)


class EditorTestCase(TestCase):
    def setUp(self):
        organization = Organization.objects.create(name='Acme', email='org@acme.example')
        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=organization)
        self.section = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Communication')

    def add_question(self, question_type='rating', config=None, **fields):
        order = self.section.questions.count()
        return Question.objects.create(
            section=self.section,
            question_text=f'Question {order}',
            question_type=question_type,
            config={'min': 1, 'max': 5} if config is None else config,
            order=order,
            **fields,
        )

    def add_options(self, question, labels):
        return [
            AnswerOption.objects.create(question=question, order=order, label=label)
            for order, label in enumerate(labels)
        ]


class SaveQuestionTests(EditorTestCase):
    def save(self, question, **fields):
        return save_question(self.questionnaire, post(**fields), question=question)

    def test_a_new_question_counts_for_no_level(self):
        question = save_question(
            self.questionnaire,
            post(question_text='Explains decisions', question_type='rating', rating_count='5'),
            section=self.section,
        )

        self.assertNotIn('dreyfus_mapping', question.config)
        self.assertEqual(question.config['max'], 5)

    def test_a_score_can_have_two_to_seven_options(self):
        question = self.add_question()

        self.save(question, question_text='Explains decisions', question_type='rating', rating_count='4')
        self.assertEqual(question.config['max'], 4)

        for count in ('1', '8', 'x'):
            with self.subTest(count=count), self.assertRaises(EditorError):
                self.save(question, question_text='Explains decisions', question_type='rating', rating_count=count)

    def test_an_empty_text_keeps_the_stored_question(self):
        question = self.add_question()

        for fields in ({'question_text': '   ', 'question_type': 'rating'}, {'question_type': 'grid'}):
            with self.subTest(fields=fields):
                with self.assertRaises(EditorError):
                    self.save(question, **{'question_text': 'Explains decisions', 'rating_count': '5', **fields})

                question.refresh_from_db()
                self.assertEqual(question.question_text, 'Question 0')
                self.assertEqual(question.question_type, 'rating')

    def answer(self, question):
        cycle = ReviewCycleFactory(questionnaire=self.questionnaire)
        ResponseFactory(question=question, cycle=cycle, token=ReviewerTokenFactory(cycle=cycle))

    def test_an_answered_score_keeps_its_number_of_options(self):
        question = self.add_question()
        self.answer(question)

        with self.assertRaises(EditorError):
            self.save(question, question_text='Question 0', question_type='rating', rating_count='4')

        question.refresh_from_db()
        self.assertEqual(question.config['max'], 5)

    def test_an_answered_question_cannot_become_a_score_or_a_slider(self):
        likert = self.add_question('likert', config={})
        self.answer(likert)

        for fields in ({'question_type': 'rating', 'rating_count': '5'}, {'question_type': 'scale'}):
            with self.subTest(fields=fields):
                with self.assertRaises(EditorError):
                    self.save(likert, question_text='Question 0', **fields)

                likert.refresh_from_db()
                self.assertEqual(likert.question_type, 'likert')

        rating = self.add_question()
        self.answer(rating)
        self.save(rating, question_text='Question 1', question_type='text')
        rating.refresh_from_db()
        self.assertEqual(rating.question_type, 'text')

        with self.assertRaises(EditorError):
            self.save(rating, question_text='Question 1', question_type='rating', rating_count='4')

    def test_default_labels_follow_the_number_of_options(self):
        question = self.add_question(labels=D)

        self.save(
            question,
            question_text='Question 0',
            question_type='rating',
            rating_count='4',
            **{f'rating_label_{key}': label for key, label in D.items()},
        )
        self.assertEqual(question.labels, {'1': 'Strongly Disagree', '4': 'Strongly Agree'})

        self.save(
            question,
            question_text='Question 0',
            question_type='rating',
            rating_count='3',
            rating_label_1='Strongly Disagree',
            rating_label_4='Strongly Agree',
        )
        self.assertEqual(question.labels, {'1': 'Strongly Disagree', '3': 'Strongly Agree'})

    def test_cleared_labels_stay_cleared(self):
        question = self.add_question(labels={'1': 'Never', '5': 'Always'})

        self.save(
            question,
            question_text='Question 0',
            question_type='rating',
            rating_count='5',
            **{f'rating_label_{value}': '' for value in range(1, 6)},
        )
        self.assertEqual(question.labels, {})

        new = save_question(
            self.questionnaire,
            post(question_text='Listens well', question_type='rating', rating_count='5'),
            section=self.section,
        )
        self.assertEqual(new.labels, D)

    def test_fewer_options_drop_the_labels_above_and_their_translations(self):
        typed = {f'{value}': f'Label {value}' for value in range(1, 6)}
        described = {f'{value}': f'Description {value}' for value in range(1, 6)}
        question = self.add_question(labels=typed, descriptions=described)
        QuestionTranslation.objects.create(
            question=question,
            language='de',
            labels={key: f'Bezeichnung {key}' for key in typed},
            descriptions={key: f'Beschreibung {key}' for key in typed},
            source_checksums={
                **{f'labels.{key}': 'abc' for key in typed},
                **{f'descriptions.{key}': 'abc' for key in typed},
                'question_text': 'abc',
            },
        )

        self.save(
            question,
            question_text='Question 0',
            question_type='rating',
            rating_count='3',
            rating_descriptions='on',
            **{f'rating_label_{key}': label for key, label in typed.items()},
            **{f'rating_description_{key}': text for key, text in described.items()},
        )

        translation = question.translations.get()
        self.assertEqual(sorted(question.labels), ['1', '2', '3'])
        self.assertEqual(sorted(question.descriptions), ['1', '2', '3'])
        self.assertEqual(sorted(translation.labels), ['1', '2', '3'])
        self.assertEqual(sorted(translation.descriptions), ['1', '2', '3'])
        self.assertEqual(sorted(translation.source_checksums), [
            'descriptions.1', 'descriptions.2', 'descriptions.3', 'labels.1', 'labels.2', 'labels.3', 'question_text',
        ])

    def test_another_type_removes_the_answers_of_the_old_one(self):
        question = self.add_question('likert', config={'reverse_scored': True})
        options = self.add_options(question, ['Never', 'Rarely', 'Often', 'Always'])

        self.save(
            question,
            question_text='Question 0',
            question_type='text',
            likert_option_id=[f'{option.id}' for option in options],
            likert_option_label=[option.label for option in options],
            reverse_scored='on',
        )

        self.assertFalse(AnswerOption.objects.filter(question=question).exists())
        self.assertNotIn('reverse_scored', question.config)

    def test_a_switch_back_stores_the_answers_as_new_options(self):
        question = self.add_question('likert', config={})
        options = self.add_options(question, ['Never', 'Rarely', 'Often', 'Always'])
        ids = [f'{option.id}' for option in options]
        labels = [option.label for option in options]
        self.save(question, question_text='Question 0', question_type='text')

        self.save(
            question,
            question_text='Question 0',
            question_type='likert',
            likert_option_id=ids,
            likert_option_label=labels,
        )

        stored = list(question.options.all())
        self.assertEqual([option.label for option in stored], labels)
        self.assertFalse({f'{option.id}' for option in stored} & set(ids))

    def test_weights_and_chart_settings_survive_a_save(self):
        question = self.add_question(config={
            'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1.5}, 'chart_weight': 2, 'exclude_from_charts': True,
        })

        self.save(question, question_text='Question 0', question_type='rating', rating_count='5')

        question.refresh_from_db()
        self.assertEqual(question.config['dreyfus_mapping'], {'skill': 1.5})
        self.assertEqual(question.config['chart_weight'], 2)
        self.assertIs(question.config['exclude_from_charts'], True)

    def test_pick_one_is_a_list_unless_the_box_is_off(self):
        question = self.add_question('single_choice', config={})
        fields = {'question_text': 'Question 0', 'question_type': 'single_choice', 'choice_option_id': ['', ''],
                  'choice_option_label': ['Yes', 'No']}

        self.save(question, display_list='on', **fields)
        self.assertNotIn('display', question.config)

        self.save(question, **fields)
        self.assertEqual(question.config['display'], 'dropdown')

    def test_did_not_observe_is_stored_for_scores_and_likerts_only(self):
        question = self.add_question()
        fields = {'question_text': 'Question 0', 'question_type': 'rating', 'rating_count': '5'}

        self.save(question, **fields)
        self.assertIs(question.config['did_not_observe'], False)

        self.save(question, did_not_observe='on', **fields)
        self.assertIs(question.config['did_not_observe'], True)

        self.save(question, question_text='Question 0', question_type='scale', did_not_observe='on')
        self.assertNotIn('did_not_observe', question.config)

    def test_advice_stays_when_the_form_does_not_show_it(self):
        stored = [{'key': 'a', 'text': 'Practise', 'threshold': 3.0}]
        question = self.add_question(action_items=stored)
        fields = {'question_text': 'Question 0', 'question_type': 'rating', 'rating_count': '5'}

        self.save(question, **fields)
        question.refresh_from_db()
        self.assertEqual(question.action_items, stored)

        self.save(question, action_items_posted='1', **fields)
        question.refresh_from_db()
        self.assertEqual(question.action_items, [])

        question.action_items = stored
        question.save()
        self.save(
            question,
            action_items_posted='1',
            **{
                'action_items[0][text]': 'Practise more',
                'action_items[0][key]': 'a',
                'action_items[0][threshold]': '2.5',
            },
            **fields,
        )
        question.refresh_from_db()
        self.assertEqual(question.action_items, [{'key': 'a', 'text': 'Practise more', 'threshold': 2.5}])

    def test_a_slider_needs_a_range(self):
        question = self.add_question()

        for fields in ({'scale_min': '5', 'scale_max': '5'}, {'scale_step': '0'}):
            with self.subTest(fields=fields), self.assertRaises(EditorError):
                self.save(question, question_text='Question 0', question_type='scale', **fields)


class WeightTests(EditorTestCase):
    def test_a_weight_of_zero_leaves_no_trace(self):
        question = self.add_question()

        set_weight(question, 'skill', 1.5)
        self.assertEqual(question.config['dreyfus_mapping'], {'skill': 1.5})

        set_weight(question, 'skill', 0)
        self.assertNotIn('dreyfus_mapping', question.config)

    def test_only_the_five_weights_and_two_models_exist(self):
        question = self.add_question()

        for model, weight in (('skill', 3), ('disc', 1)):
            with self.subTest(model=model, weight=weight), self.assertRaises(EditorError):
                set_weight(question, model, weight)

    def test_the_older_mapping_format_keeps_the_other_weight(self):
        question = self.add_question(config={'dreyfus_mapping': {'dimension': 'skill', 'weight': 1.5}})

        set_weight(question, 'agency', 2)

        question.refresh_from_db()
        self.assertEqual(question.config['dreyfus_mapping'], {'skill': 1.5, 'agency': 2})


class ClearModelTests(EditorTestCase):
    def test_clearing_a_model_keeps_the_other(self):
        questions = [self.add_question(config={'dreyfus_mapping': {'skill': 1, 'agency': 2}}) for _ in range(2)]

        clear_model(self.questionnaire, 'skill')

        for question in questions:
            question.refresh_from_db()
            self.assertEqual(question.config['dreyfus_mapping'], {'agency': 2})

        self.assertEqual(Questionnaire.objects.get(pk=self.questionnaire.pk).dreyfus_dimensions, (False, True))


class DidNotObserveTests(EditorTestCase):
    def test_one_switch_sets_every_score_and_likert(self):
        rating = self.add_question()
        self.add_question('likert', config={})
        text = self.add_question('text', config={})

        set_did_not_observe(self.questionnaire, False)

        self.assertEqual(did_not_observe_state(self.questionnaire), 'off')
        text.refresh_from_db()
        self.assertEqual(text.config, {})

        rating.config['did_not_observe'] = True
        rating.save()
        self.assertEqual(did_not_observe_state(self.questionnaire), 'mixed')

    def test_a_questionnaire_without_scores_or_likerts_counts_as_on(self):
        self.add_question('text', config={})

        self.assertEqual(did_not_observe_state(self.questionnaire), 'on')


class ReportPreviewTests(EditorTestCase):
    def add_topic(self, title, question_type='rating', count=1, config=None):
        section = QuestionSection.objects.create(
            questionnaire=self.questionnaire, title=title, order=self.questionnaire.sections.count()
        )
        for order in range(count):
            Question.objects.create(
                section=section,
                question_text=f'{title} {order}',
                question_type=question_type,
                config={'min': 1, 'max': 5} if config is None else config,
                order=order,
            )

        return section

    def preview(self, shown=frozenset()):
        return report_preview(Questionnaire.objects.get(pk=self.questionnaire.pk), set(shown))

    def test_three_scored_topics_make_a_radar_two_get_an_overall_point_one_gives_bars(self):
        self.section.delete()
        topics = [self.add_topic(title) for title in ('Delivery', 'Quality', 'Teamwork')]

        preview = self.preview()
        self.assertEqual(preview['case'], 'radar')
        self.assertEqual(list(preview['radar_axes']), ['Delivery', 'Quality', 'Teamwork'])

        topics[2].delete()
        preview = self.preview()
        self.assertEqual(preview['case'], 'overall')
        self.assertEqual(list(preview['radar_axes']), ['Delivery', 'Quality', 'Overall'])

        topics[1].delete()
        preview = self.preview()
        self.assertEqual(preview['case'], 'bars')
        self.assertIsNone(preview['radar_axes'])

    def test_two_topics_with_one_title_are_one_point(self):
        self.add_question()
        self.add_topic('Communication')
        self.add_topic('Delivery')

        preview = self.preview()
        self.assertEqual(preview['case'], 'overall')
        self.assertEqual(len(preview['chart']['section_scores']), 2)
        self.assertEqual(len(preview['radar_axes']), 3)
        self.assertIn('Overall', preview['radar_axes'])
        self.assertEqual([topic['point'] for topic in preview['topics']], [True, True, True])

    def test_a_topic_with_only_written_answers_is_no_point(self):
        self.section.delete()
        written = self.add_topic('Comments', 'text', count=2, config={})

        preview = self.preview()
        self.assertEqual(
            preview['topics'],
            [{'id': written.id, 'title': 'Comments', 'questions': 2, 'counting': 0, 'point': False}],
        )
        self.assertNotIn('Comments', preview['chart']['section_scores'])
        self.assertEqual(preview['case'], 'none')

    def test_a_point_shows_the_mean_of_its_example_scores_per_reviewer_group(self):
        a = self.add_question()
        b = self.add_question()
        mean = (example_score(a) + example_score(b)) / 2

        scores = self.preview()['chart']['section_scores']['Communication']
        self.assertEqual(
            scores,
            {
                'self': round(mean - 0.2, 2),
                'peer': round(mean, 2),
                'manager': round(mean + 0.2, 2),
                'direct_report': round(mean + 0.1, 2),
            },
        )

    def test_an_example_score_depends_only_on_the_question_id(self):
        question = self.add_question()
        score = example_score(question)

        question.question_text = 'Another text'
        self.assertEqual(example_score(question), score)
        self.assertTrue(3.0 <= score <= 4.6)

    def test_a_level_is_the_weighted_average_of_the_questions_that_count(self):
        a = self.add_question(config={'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1}})
        b = self.add_question(config={'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 2}})
        self.add_question('text', config={'dreyfus_mapping': {'skill': 2}})

        preview = self.preview()
        level = preview['levels'][0]
        self.assertEqual(level['model'], 'skill')
        self.assertEqual([row['question'] for row in level['rows']], [a, b])
        self.assertEqual(level['weight_sum'], 3)
        self.assertEqual(level['level'], round((example_score(a) + 2 * example_score(b)) / 3, 2))
        self.assertEqual((level['low'], level['high']), (level['stage'] - 0.5, level['stage'] + 0.5))
        self.assertEqual(level['profile']['skill_level'], level['level'])
        self.assertEqual(level['profile']['stage'], level['stage'])

    def test_a_model_ticked_in_this_visit_shows_without_questions(self):
        self.add_question()

        levels = self.preview(shown={'agency'})['levels']
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0]['model'], 'agency')
        self.assertEqual(levels[0]['rows'], [])
        self.assertIsNone(levels[0]['level'])
        self.assertIsNone(levels[0]['stage'])
        self.assertIsNone(levels[0]['profile'])

    def test_an_older_mapping_turns_its_model_on(self):
        self.add_question(config={'min': 1, 'max': 5, 'dreyfus_mapping': {'dimension': 'skill', 'weight': 1.5}})

        levels = self.preview()['levels']
        self.assertEqual([level['model'] for level in levels], ['skill'])
        self.assertEqual([row['weight'] for row in levels[0]['rows']], [1.5])

    def test_the_two_models_stand_alone(self):
        self.add_question(config={'min': 1, 'max': 5, 'dreyfus_mapping': {'agency': 1}})

        levels = self.preview()['levels']
        self.assertEqual([level['model'] for level in levels], ['agency'])
        self.assertEqual(levels[0]['profile']['agency_level'], levels[0]['level'])
