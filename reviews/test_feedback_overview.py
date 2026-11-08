"""Tests for the reviewer's personal overview page behind the signed link.

`reviews.services.send_email` is patched, as in test_grouped_invitations: core.email builds its
own SMTP backend and bypasses the test outbox.
"""
import re
import time
from unittest.mock import patch

from django.core import signing
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.factories import RevieweeFactory, UserProfileFactory
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory


def overview_path(email, organization, days_ago=0):
    with patch('django.core.signing.time.time', return_value=time.time() - days_ago * 86400):
        signed = signing.dumps({'e': email, 'o': organization.id}, salt='feedback-overview')
    return reverse('reviews:feedback_overview', kwargs={'signed': signed})


class FeedbackOverviewTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        # The setup middleware sends every request to the setup wizard until a profile exists.
        UserProfileFactory(organization=self.org)
        self.email = 'carol@example.com'

    def cycle(self, name, organization=None, status='active'):
        organization = organization or self.org
        return ReviewCycleFactory(
            reviewee=RevieweeFactory(organization=organization, name=name),
            questionnaire=QuestionnaireFactory(organization=organization),
            created_by=UserFactory(),
            status=status,
        )

    def test_lists_open_and_done_tokens(self):
        open_token = ReviewerTokenFactory(cycle=self.cycle('Alice'), category='peer', reviewer_email=self.email)
        done_token = ReviewerTokenFactory(
            cycle=self.cycle('Bob'), category='manager', reviewer_email=self.email, completed_at=timezone.now(),
        )

        response = self.client.get(overview_path(self.email, self.org))

        self.assertEqual(response.status_code, 200)
        items = response.context['items']
        self.assertEqual([item['token'] for item in items], [open_token, done_token])
        self.assertEqual([item['state'] for item in items], ['start', 'done'])
        self.assertContains(response, reverse('reviews:feedback_form', kwargs={'token': open_token.token}))
        self.assertNotContains(response, reverse('reviews:feedback_form', kwargs={'token': done_token.token}))

    def test_done_tokens_come_after_open_ones(self):
        ReviewerTokenFactory(cycle=self.cycle('Alice'), category='peer', reviewer_email=self.email, completed_at=timezone.now())
        open_token = ReviewerTokenFactory(cycle=self.cycle('Bob'), category='peer', reviewer_email=self.email)

        response = self.client.get(overview_path(self.email, self.org))

        self.assertEqual(response.context['items'][0]['token'], open_token)

    def test_tampered_link_is_not_found(self):
        ReviewerTokenFactory(cycle=self.cycle('Alice'), category='peer', reviewer_email=self.email)
        path = overview_path(self.email, self.org)

        response = self.client.get(path[:-2] + 'x/')

        self.assertEqual(response.status_code, 404)

    def test_does_not_list_tokens_of_another_organization(self):
        other_org = OrganizationFactory()
        ours = ReviewerTokenFactory(cycle=self.cycle('Alice'), category='peer', reviewer_email=self.email)
        theirs = ReviewerTokenFactory(cycle=self.cycle('Zed', other_org), category='peer', reviewer_email=self.email)

        response = self.client.get(overview_path(self.email, self.org))

        self.assertEqual([item['token'] for item in response.context['items']], [ours])
        self.assertNotContains(response, str(theirs.token))

    def test_token_on_a_completed_cycle_shows_as_closed(self):
        token = ReviewerTokenFactory(
            cycle=self.cycle('Alice', status='completed'), category='peer', reviewer_email=self.email,
        )

        response = self.client.get(overview_path(self.email, self.org))

        self.assertEqual(response.context['items'][0]['state'], 'closed')
        self.assertNotContains(response, reverse('reviews:feedback_form', kwargs={'token': token.token}))

    def test_claimed_token_offers_to_continue(self):
        ReviewerTokenFactory(
            cycle=self.cycle('Alice'), category='peer', reviewer_email=self.email, claimed_at=timezone.now(),
        )

        response = self.client.get(overview_path(self.email, self.org))

        self.assertEqual(response.context['items'][0]['state'], 'continue')

    def test_groups_own_self_assessments_apart_from_the_others(self):
        own = ReviewerTokenFactory(cycle=self.cycle('Carol'), category='self', reviewer_email=self.email)
        boss = ReviewerTokenFactory(cycle=self.cycle('Dave'), category='direct_report', reviewer_email=self.email)

        response = self.client.get(overview_path(self.email, self.org))

        self.assertEqual([item['token'] for item in response.context['self_items']], [own])
        self.assertEqual([item['token'] for item in response.context['other_items']], [boss])
        self.assertEqual(str(response.context['other_items'][0]['relation']), 'your manager')
        self.assertEqual(response.context['total_count'], 2)


class ExpiredOverviewLinkTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        UserProfileFactory(organization=self.org)
        self.email = 'carol@example.com'
        self.token = ReviewerTokenFactory(
            cycle=ReviewCycleFactory(
                reviewee=RevieweeFactory(organization=self.org, name='Alice'),
                questionnaire=QuestionnaireFactory(organization=self.org),
                created_by=UserFactory(),
            ),
            category='peer',
            reviewer_email=self.email,
        )
        self.form_path = reverse('reviews:feedback_form', kwargs={'token': self.token.token})

    def test_a_link_within_thirty_days_still_opens_the_overview(self):
        response = self.client.get(overview_path(self.email, self.org, days_ago=29))

        self.assertTemplateUsed(response, 'reviews/feedback_overview.html')
        self.assertContains(response, self.form_path)

    def test_an_expired_link_offers_a_new_one_instead_of_the_forms(self):
        response = self.client.get(overview_path(self.email, self.org, days_ago=31))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reviews/feedback_overview_expired.html')
        self.assertContains(response, 'This link has expired')
        self.assertContains(response, 'Send me a new link')
        self.assertNotContains(response, self.form_path)

    @patch('reviews.services.send_email')
    def test_requesting_a_new_link_mails_one_that_works(self, mock_send_email):
        response = self.client.post(overview_path(self.email, self.org, days_ago=31))

        self.assertContains(response, 'If we have forms for this address, a new link is on its way.')
        self.assertEqual(mock_send_email.call_count, 1)
        kwargs = mock_send_email.call_args.kwargs
        self.assertEqual(kwargs['recipient_list'], [self.email])
        url = re.search(r'https?://\S+/feedback/overview/\S+/', kwargs['message']).group()
        self.assertIn(url, kwargs['html_message'])

        fresh = self.client.get('/' + url.split('/', 3)[3])
        self.assertTemplateUsed(fresh, 'reviews/feedback_overview.html')
        self.assertContains(fresh, self.form_path)

    @patch('reviews.services.send_email')
    def test_an_address_without_forms_gets_the_same_page_and_no_email(self, mock_send_email):
        response = self.client.post(overview_path('nobody@example.com', self.org, days_ago=31))

        self.assertContains(response, 'If we have forms for this address, a new link is on its way.')
        mock_send_email.assert_not_called()

    def test_a_tampered_expired_link_is_not_found(self):
        path = overview_path(self.email, self.org, days_ago=31)

        self.assertEqual(self.client.get(path[:-2] + 'x/').status_code, 404)
        self.assertEqual(self.client.post(path[:-2] + 'x/').status_code, 404)
