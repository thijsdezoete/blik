"""Tests for the reviewer's personal overview page behind the signed link."""
from django.core import signing
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.factories import RevieweeFactory, UserProfileFactory
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory


def overview_path(email, organization):
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
