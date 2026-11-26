from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from questionnaires.models import Question, QuestionSection
from reports.models import Report
from reviews.models import Response

from .factories import ReviewCycleFactory, ReviewerTokenFactory
from .templatetags.feedback_tags import browser_number


class LastSubmissionTests(TestCase):
    def test_last_submission_closes_cycle_without_generating_report(self):
        cycle = ReviewCycleFactory(status='active')
        organization = cycle.reviewee.organization
        organization.auto_send_report_email = True
        organization.save()
        # Without a user and an organization, the setup middleware redirects every request
        UserProfile.objects.create(user=User.objects.create_user(username='admin'), organization=organization)
        token = ReviewerTokenFactory(cycle=cycle, reviewer_email='peer@example.org')

        response = self.client.post(reverse('reviews:submit_feedback', args=[token.token]))

        self.assertEqual(response.status_code, 200)
        cycle.refresh_from_db()
        self.assertEqual(cycle.status, 'completed')
        self.assertIsNone(cycle.report_finalized_at)
        self.assertFalse(Report.objects.filter(cycle=cycle).exists())
        self.assertNotIn([cycle.reviewee.email], [message.to for message in mail.outbox])


class SliderAnswerTests(TestCase):
    """A slider takes every number of its range, also between whole numbers when its step is below 1."""

    def setUp(self):
        cycle = ReviewCycleFactory(status='active')
        UserProfile.objects.create(user=User.objects.create_user(username='admin'),
                                   organization=cycle.reviewee.organization)
        # A second, open token: the cycle must not close on the first submission
        ReviewerTokenFactory(cycle=cycle, reviewer_email='other@acme.example')
        self.token = ReviewerTokenFactory(cycle=cycle, reviewer_email='peer@acme.example')
        section = QuestionSection.objects.create(questionnaire=cycle.questionnaire, title='Trust', order=50)
        self.question = Question.objects.create(
            section=section, question_text='How much do you trust {name}?', question_type='scale',
            config={'min': 1, 'max': 5, 'step': 0.5}, required=False, order=0,
        )

    def submit(self, value):
        return self.client.post(reverse('reviews:submit_feedback', args=[self.token.token]),
                                {f'question_{self.question.id}': value})

    def stored(self):
        return Response.objects.get(question=self.question).answer_data

    def test_a_number_between_whole_numbers_is_stored_as_it_is(self):
        self.assertEqual(self.submit('3.5').status_code, 200)
        self.assertEqual(self.stored(), {'value': 3.5})

    def test_a_whole_number_stays_a_whole_number(self):
        self.assertEqual(self.submit('4').status_code, 200)
        self.assertEqual(self.stored(), {'value': 4})
        self.assertIs(type(self.stored()['value']), int)

    def test_a_number_outside_the_range_or_no_number_is_refused(self):
        for value in ('5.5', '0.5', 'nan', 'inf', '3,5', 'much'):
            with self.subTest(value=value):
                self.assertEqual(self.submit(value).status_code, 400)
                self.assertFalse(Response.objects.filter(question=self.question).exists())


class BrowserNumberTests(TestCase):
    def test_a_number_for_the_browser_has_a_point_in_every_language(self):
        # In German a template writes 0.5 as "0,5", which a range input does not understand
        from django.utils import translation

        with translation.override('de'):
            self.assertEqual(browser_number(0.5), '0.5')
            self.assertEqual(browser_number(3), '3')
            self.assertEqual(browser_number(2.0), '2')
            self.assertEqual(browser_number(None), '')

    def test_the_slider_of_the_form_gets_its_step_with_a_point(self):
        from django.template.loader import render_to_string
        from django.utils import translation

        question = Question(question_text='How much do you trust {name}?', question_type='scale',
                            config={'min': 1, 'max': 5, 'step': 0.5})

        with translation.override('nl'):
            html = render_to_string('reviews/_question.html', {
                'question': question, 'name': 'Alex', 'existing_responses': {'None': 3.5},
            })

        self.assertIn('step="0.5"', html)
        self.assertIn('value="3.5"', html)
        self.assertNotIn('0,5', html)
        self.assertNotIn('3,5', html)
