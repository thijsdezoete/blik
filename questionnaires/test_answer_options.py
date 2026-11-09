"""Answer options and labels: answers refer to options by id, the editor posts them as rows."""
from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from api.models import APIToken
from core.models import Organization
from core.upgrade_steps import move_question_texts
from questionnaires.answer_options import save_options
from questionnaires.legacy_config import config_with_texts, move_texts_out_of_config
from questionnaires.models import Question, QuestionSection, Questionnaire
from questionnaires.signals import clone_questionnaire_for_organization
from reports.services import generate_report
from reviews.models import Response, ReviewCycle, ReviewerToken

SCALE = ['Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree']


class AnswerOptionTestCase(TestCase):

    def setUp(self):
        ensure_permission_groups()
        self.organization = Organization.objects.create(
            name='Org',
            email='org@example.com',
            min_responses_for_anonymity=1,
        )
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'pw')
        UserProfile.objects.create(user=self.admin, organization=self.organization)
        assign_organization_admin(self.admin)

        self.questionnaire = Questionnaire.objects.create(name='Q', organization=self.organization)
        self.section = QuestionSection.objects.create(questionnaire=self.questionnaire, title='S', order=1)
        self.likert = self.create_question('Likert', 'likert', [(label, None) for label in SCALE])
        self.choice = self.create_question('Choice', 'single_choice', [('Low', 1), ('High', 5)], scoring_enabled=True)
        self.multi = self.create_question('Multi', 'multiple_choice', [('Calm', None), ('Kind', None), ('Fast', None)])
        reviewee = Reviewee.objects.create(name='Rita', email='rita@example.com', organization=self.organization)
        self.cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=self.questionnaire)

    def create_question(self, text, question_type, options, **config):
        question = Question.objects.create(
            section=self.section,
            question_text=text,
            question_type=question_type,
            config=config,
            required=False,
            order=self.section.questions.count(),
        )
        save_options(question, [(None, label, weight) for label, weight in options])

        return question

    def create_old_question(self, question_type, config):
        """A question as saved before answer options and Question.labels existed."""

        return Question.objects.create(
            section=self.section,
            question_text=question_type,
            question_type=question_type,
            config=config,
            order=self.section.questions.count(),
        )

    def create_token(self):
        return ReviewerToken.objects.create(cycle=self.cycle, category='peer')

    def respond(self, question, value):
        token = self.create_token()

        return Response.objects.create(
            cycle=self.cycle,
            question=question,
            token=token,
            category='peer',
            answer_data={'value': value},
        )

    @staticmethod
    def option_id(question, label):
        return question.options.get(label=label).id

    @staticmethod
    def option_labels(question):
        return list(question.options.values_list('label', flat=True))

    @staticmethod
    def stored_answers(token):
        responses = Response.objects.filter(token=token)

        return {response.question_id: response.answer_data['value'] for response in responses}


class SaveOptionsTest(AnswerOptionTestCase):

    def test_rows_become_options_in_their_order(self):
        self.assertEqual(self.option_labels(self.likert), SCALE)
        self.assertEqual(list(self.choice.options.values_list('label', 'weight')), [('Low', 1), ('High', 5)])

    def test_a_row_with_the_id_of_an_option_updates_it(self):
        agree = self.option_id(self.likert, 'Agree')
        rows = [(option.id, option.label, None) for option in self.likert.options.all()]
        rows[3] = (agree, 'Rather agree', None)

        save_options(self.likert, rows)

        self.assertEqual(self.likert.options.get(id=agree).label, 'Rather agree')
        self.assertEqual(self.likert.options.count(), 5)

    def test_rows_can_be_moved_added_and_removed(self):
        low, high = self.option_id(self.choice, 'Low'), self.option_id(self.choice, 'High')

        save_options(self.choice, [(high, 'High', 5), (None, 'Medium', 3)])

        self.assertEqual(list(self.choice.options.values_list('label', 'weight')), [('High', 5), ('Medium', 3)])
        self.assertEqual(self.choice.options.first().id, high)
        self.assertFalse(self.choice.options.filter(id=low).exists())


class EditorTest(AnswerOptionTestCase):

    def edit(self, **data):
        self.client.force_login(self.admin)

        return self.client.post(reverse('questionnaire_edit', args=[self.questionnaire.uuid]), data)

    def test_adding_a_question_stores_its_rows(self):
        self.edit(
            action='add_question',
            section_id=self.section.id,
            question_type='single_choice',
            question_text='Seniority',
            enable_scoring='on',
            choice_option_id=['', ''],
            choice_option_label=['Novice', 'Expert'],
            choice_option_weight=['1', '5'],
        )

        question = Question.objects.get(question_text='Seniority')
        self.assertEqual(list(question.options.values_list('label', 'weight')), [('Novice', 1), ('Expert', 5)])
        self.assertEqual(question.config, {'scoring_enabled': True})

    def test_editing_keeps_the_options_and_the_answers_given(self):
        answer = self.respond(self.likert, self.option_id(self.likert, 'Agree'))
        options = list(reversed(self.likert.options.all()))

        self.edit(
            action='edit_question',
            question_id=self.likert.id,
            question_type='likert',
            question_text='Likert',
            likert_option_id=[f'{option.id}' for option in options],
            likert_option_label=[option.label.replace('Agree', 'Concur') for option in options],
        )

        self.assertEqual(self.option_labels(self.likert)[:2], ['Strongly Concur', 'Concur'])
        self.assertEqual(self.likert.options.get(id=answer.answer_data['value']).label, 'Concur')

    def test_an_invalid_weight_disables_scoring(self):
        self.edit(
            action='edit_question',
            question_id=self.choice.id,
            question_type='single_choice',
            question_text='Choice',
            enable_scoring='on',
            choice_option_id=[f'{option.id}' for option in self.choice.options.all()],
            choice_option_label=['Low', 'High'],
            choice_option_weight=['1', ''],
        )

        self.choice.refresh_from_db()
        self.assertNotIn('scoring_enabled', self.choice.config)
        self.assertEqual(list(self.choice.options.values_list('label', 'weight')), [('Low', None), ('High', None)])

    def test_another_type_drops_the_options(self):
        self.edit(action='edit_question', question_id=self.multi.id, question_type='text', question_text='Multi')

        self.assertFalse(self.multi.options.exists())

    def test_rating_and_scale_labels_are_stored_without_the_empty_ones(self):
        self.edit(
            action='add_question',
            section_id=self.section.id,
            question_type='rating',
            question_text='Rating',
            rating_label_1='Rarely',
            rating_label_5='Always',
        )
        self.edit(
            action='add_question',
            section_id=self.section.id,
            question_type='scale',
            question_text='Scale',
            scale_min_label='Drained',
        )

        self.assertEqual(Question.objects.get(question_text='Rating').labels, {'1': 'Rarely', '5': 'Always'})
        self.assertEqual(Question.objects.get(question_text='Scale').labels, {'min': 'Drained'})

    def test_rating_descriptions_are_stored_without_the_empty_ones(self):
        self.edit(
            action='add_question',
            section_id=self.section.id,
            question_type='rating',
            question_text='Timeliness',
            rating_descriptions='on',
            rating_description_1='Almost never on time',
            rating_description_2='  ',
        )

        self.assertEqual(Question.objects.get(question_text='Timeliness').descriptions, {'1': 'Almost never on time'})

    def test_switching_the_rating_descriptions_off_drops_them(self):
        question = Question.objects.create(
            section=self.section,
            question_text='Timeliness',
            question_type='rating',
            descriptions={'1': 'Almost never on time'},
            order=self.section.questions.count(),
        )

        self.edit(
            action='edit_question',
            question_id=question.id,
            question_type='rating',
            question_text='Timeliness',
            rating_description_1='Almost never on time',
        )

        question.refresh_from_db()
        self.assertEqual(question.descriptions, {})

    def test_another_type_drops_the_rating_descriptions(self):
        question = Question.objects.create(
            section=self.section,
            question_text='Timeliness',
            question_type='rating',
            descriptions={'1': 'Almost never on time'},
            order=self.section.questions.count(),
        )

        self.edit(action='edit_question', question_id=question.id, question_type='text', question_text='Timeliness')

        question.refresh_from_db()
        self.assertEqual(question.descriptions, {})


class ConfigTextsTest(AnswerOptionTestCase):

    def test_options_kept_in_the_config_become_rows(self):
        config = {'choices': ['Low', 'High'], 'weights': [1, 5], 'scoring_enabled': True}
        question = self.create_old_question('single_choice', config)

        move_texts_out_of_config(question)
        move_texts_out_of_config(question)

        self.assertEqual(list(question.options.values_list('label', 'weight')), [('Low', 1), ('High', 5)])
        self.assertEqual(question.config, {'scoring_enabled': True})

    def test_labels_kept_in_the_config_move_to_their_field(self):
        rating = self.create_old_question('rating', {'min': 1, 'max': 5, 'labels': {'1': 'Poor', '5': 'Great'}})
        scale = self.create_old_question('scale', {'min': 0, 'max': 10, 'min_label': 'Low', 'max_label': 'High'})

        move_texts_out_of_config(rating)
        move_texts_out_of_config(scale)

        self.assertEqual((rating.config, rating.labels), ({'min': 1, 'max': 5}, {'1': 'Poor', '5': 'Great'}))
        self.assertEqual((scale.config, scale.labels), ({'min': 0, 'max': 10}, {'min': 'Low', 'max': 'High'}))

    def test_the_api_reads_the_texts_from_the_config_as_before(self):
        rating = self.create_old_question('rating', {'min': 1, 'max': 5, 'labels': {'1': 'Poor', '5': 'Great'}})
        scale = self.create_old_question('scale', {'min': 0, 'max': 10, 'max_label': 'High'})
        before = [rating.config, scale.config, config_with_texts(self.choice)]

        move_texts_out_of_config(rating)
        move_texts_out_of_config(scale)

        self.assertEqual([config_with_texts(rating), config_with_texts(scale)], before[:2])
        self.assertEqual(before[2], {'scoring_enabled': True, 'choices': ['Low', 'High'], 'weights': [1, 5]})

    def test_cloning_into_a_new_organization_copies_the_options(self):
        other = Organization.objects.create(name='Other', email='other@example.com')
        clone = clone_questionnaire_for_organization(self.questionnaire, other)

        cloned_likert = Question.objects.get(section__questionnaire=clone, question_type='likert')
        self.assertEqual(self.option_labels(cloned_likert), SCALE)
        self.assertNotEqual(cloned_likert.options.first().id, self.likert.options.first().id)


class UpgradeStepTest(AnswerOptionTestCase):

    def test_labels_become_option_ids_and_unknown_answers_are_kept(self):
        likert = self.create_old_question('likert', {'scale': SCALE})
        multi = self.create_old_question('multiple_choice', {'choices': ['Calm', 'Kind', 'Fast']})
        text = self.create_old_question('text', {})
        agree = self.respond(likert, 'Agree')
        reworded = self.respond(likert, 'Totally agree')
        chosen = self.respond(multi, ['Calm', 'Gone', 'Fast'])
        written = self.respond(text, 'Agree')

        out = StringIO()
        move_question_texts(out)

        for response in [agree, reworded, chosen, written]:
            response.refresh_from_db()

        calm, fast = self.option_id(multi, 'Calm'), self.option_id(multi, 'Fast')
        self.assertEqual(agree.answer_data, {'value': self.option_id(likert, 'Agree')})
        self.assertEqual(reworded.answer_data, {'value': None, 'unmapped': ['Totally agree']})
        self.assertEqual(chosen.answer_data, {'value': [calm, fast], 'unmapped': ['Gone']})
        self.assertEqual(written.answer_data, {'value': 'Agree'})
        self.assertIn('Mapped 1 response(s), 2 with unmapped answers.', out.getvalue())

    def test_rating_labels_move_out_of_the_config(self):
        rating = self.create_old_question('rating', {'min': 1, 'max': 5, 'labels': {'1': 'Poor'}})

        move_question_texts(StringIO())

        rating.refresh_from_db()
        self.assertEqual((rating.config, rating.labels), ({'min': 1, 'max': 5}, {'1': 'Poor'}))

    def test_numeric_likert_answers_map_to_their_position(self):
        likert = self.create_old_question('likert', {'scale': SCALE})
        fourth = self.respond(likert, 4)
        too_high = self.respond(likert, 9)

        move_question_texts(StringIO())

        fourth.refresh_from_db()
        too_high.refresh_from_db()
        self.assertEqual(fourth.answer_data, {'value': self.option_id(likert, 'Agree')})
        self.assertEqual(too_high.answer_data, {'value': None, 'unmapped': [9]})


class FeedbackFormTest(AnswerOptionTestCase):

    def test_form_offers_option_ids_and_stores_them(self):
        token = self.create_token()
        agree = self.option_id(self.likert, 'Agree')
        form = self.client.get(reverse('reviews:feedback_form', args=[token.token]))
        self.assertContains(form, f'value="{agree}"')
        self.assertNotContains(form, 'value="Agree"')

        calm, kind = self.option_id(self.multi, 'Calm'), self.option_id(self.multi, 'Kind')
        response = self.client.post(reverse('reviews:submit_feedback', args=[token.token]), {
            f'question_{self.likert.id}': f'{agree}',
            f'question_{self.choice.id}': 'High',
            f'question_{self.multi.id}': [f'{calm}', f'{kind}'],
        })
        self.assertEqual(response.status_code, 200, response.content)

        high = self.option_id(self.choice, 'High')
        stored = {self.likert.id: agree, self.choice.id: high, self.multi.id: [calm, kind]}
        self.assertEqual(self.stored_answers(token), stored)

    def test_an_option_of_another_question_is_rejected(self):
        token = self.create_token()
        high = self.option_id(self.choice, 'High')
        response = self.client.post(reverse('reviews:submit_feedback', args=[token.token]), {
            f'question_{self.likert.id}': f'{high}',
        })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Response.objects.filter(token=token).exists())


class ReportTest(AnswerOptionTestCase):

    def view_report(self):
        self.client.force_login(self.admin)

        return self.client.get(reverse('reports:view_report', args=[self.cycle.uuid]))

    def test_counts_and_scores_survive_a_reworded_label(self):
        agree = self.option_id(self.likert, 'Agree')
        self.respond(self.likert, agree)
        self.respond(self.likert, agree)
        self.respond(self.choice, self.option_id(self.choice, 'Low'))
        self.respond(self.choice, self.option_id(self.choice, 'High'))

        rows = [(option.id, option.label, None) for option in self.likert.options.all()]
        rows[3] = (agree, 'Rather agree', None)
        save_options(self.likert, rows)

        report = generate_report(self.cycle)
        [section] = report.report_data['by_section'].values()
        likert = section['questions'][f'{self.likert.id}']['by_category']['peer']
        choice = section['questions'][f'{self.choice.id}']['by_category']['peer']
        self.assertEqual(likert['distribution'], {f'{agree}': 2})
        self.assertEqual(choice['avg'], 3.0)

        page = self.view_report()
        self.assertContains(page, '<span class="distribution-label">Rather agree</span>')
        self.assertContains(page, '2 respondents (100%)')
        self.assertContains(page, 'Strong consensus: 100% positive')

    def test_report_generated_before_options_still_renders(self):
        self.respond(self.likert, self.option_id(self.likert, 'Agree'))
        report = generate_report(self.cycle)

        # Reports from before answer options have no schema, keep the scale in the config and count answers by label
        report.report_data.pop('schema')

        for section in report.report_data['by_section'].values():
            for question in section['questions'].values():
                question.pop('options')
                question['question_config']['scale'] = SCALE

                for category in question['by_category'].values():
                    if category.get('distribution'):
                        category['distribution'] = {'Agree': 1}

        report.save()

        page = self.view_report()
        self.assertContains(page, '<span class="distribution-label">Agree</span>')
        self.assertContains(page, '1 respondent (100%)')

    def test_unmapped_answers_are_reported(self):
        self.respond(self.likert, self.option_id(self.likert, 'Agree'))
        unmapped = self.respond(self.likert, None)
        unmapped.answer_data['unmapped'] = ['Totally agree']
        unmapped.save()
        generate_report(self.cycle)

        self.assertContains(self.view_report(), '1 answer could not be matched to an option')


class ApiTest(AnswerOptionTestCase):

    def setUp(self):
        super().setUp()
        token = APIToken.objects.create(organization=self.organization, created_by=self.admin, name='T')
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token.raw_token}')
        self.url = f'/api/v1/cycles/{self.cycle.uuid}/submit_responses/'

    def submit(self, token, answers):
        responses = [{'question_uuid': f'{question.uuid}', 'value': value} for question, value in answers]

        return self.api.post(self.url, {'token': f'{token.token}', 'responses': responses}, format='json')

    def test_labels_and_ids_are_both_stored_as_ids(self):
        token = self.create_token()
        kind = self.option_id(self.multi, 'Kind')
        response = self.submit(token, [(self.likert, 'Agree'), (self.multi, [kind])])

        self.assertEqual(response.status_code, 200, response.content)
        agree = self.option_id(self.likert, 'Agree')
        self.assertEqual(self.stored_answers(token), {self.likert.id: agree, self.multi.id: [kind]})

    def test_questions_list_their_options(self):
        response = self.api.get(f'/api/v1/cycles/{self.cycle.uuid}/questionnaire/')
        [section] = response.json()['sections']

        questions = {question['question_text']: question for question in section['questions']}
        low, high = self.option_id(self.choice, 'Low'), self.option_id(self.choice, 'High')
        self.assertEqual(questions['Choice']['options'], [{'id': low, 'label': 'Low'}, {'id': high, 'label': 'High'}])
        self.assertEqual(questions['Choice']['config']['choices'], ['Low', 'High'])
        self.assertEqual(questions['Choice']['config']['weights'], [1, 5])
        self.assertEqual(questions['Likert']['config']['scale'], SCALE)

    def test_unknown_option_rejects_the_whole_request(self):
        token = self.create_token()
        response = self.submit(token, [(self.likert, 'Agree'), (self.choice, 'Medium')])

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Response.objects.filter(token=token).exists())
