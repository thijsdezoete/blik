from django.urls import reverse
from rest_framework.test import APIClient

from api.models import APIToken

from reviews.models import ReviewCycle, ReviewerToken
from subscriptions.models import RoundPurchase
from subscriptions.test_cycle_gate import CycleGateBase
from subscriptions.testing import grant, subscribe
from subscriptions.utils import FREE_REVIEWERS_PER_CYCLE, ReviewerLimit, cycle_credits

LIMIT_TEXT = 'Free accounts can invite up to 10 reviewers per review cycle.'


class ReviewerLimitBase(CycleGateBase):
    def give_free_credit(self, credits=2):
        RoundPurchase.objects.create(organization=self.org, cycles_remaining=credits,
                                     free_signup_inbox='founder@example.com')

    def new_cycle(self):
        return ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)

    def add(self, cycle, n, category='peer', **fields):
        for i in range(n):
            ReviewerToken.objects.create(cycle=cycle, category=category, **fields)


class ModelLimitTests(ReviewerLimitBase):
    def test_free_organization_cannot_add_an_eleventh_reviewer(self):
        self.give_free_credit()
        cycle = self.new_cycle()
        self.add(cycle, FREE_REVIEWERS_PER_CYCLE)
        with self.assertRaises(ReviewerLimit):
            self.add(cycle, 1, category='manager')
        self.assertEqual(cycle.tokens.count(), FREE_REVIEWERS_PER_CYCLE)

    def test_self_assessment_does_not_count(self):
        self.give_free_credit()
        cycle = self.new_cycle()
        self.add(cycle, 1, category='self')
        self.add(cycle, FREE_REVIEWERS_PER_CYCLE)
        self.assertEqual(cycle.tokens.exclude(category='self').count(), FREE_REVIEWERS_PER_CYCLE)

    def test_granted_credits_lift_the_cap(self):
        self.give_free_credit()
        grant(self.org, 1)
        cycle = self.new_cycle()
        self.add(cycle, FREE_REVIEWERS_PER_CYCLE + 1)
        self.assertEqual(cycle.tokens.count(), FREE_REVIEWERS_PER_CYCLE + 1)

    def test_subscription_lifts_the_cap(self):
        self.give_free_credit()
        subscribe(self.org)
        cycle = self.new_cycle()
        self.add(cycle, FREE_REVIEWERS_PER_CYCLE + 1)
        self.assertEqual(cycle.tokens.count(), FREE_REVIEWERS_PER_CYCLE + 1)


class ApiLimitTests(ReviewerLimitBase):
    def setUp(self):
        super().setUp()
        token = APIToken.objects.create(organization=self.org, created_by=self.user, name='t')
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token.token}')

    def test_too_many_reviewers_returns_the_message_and_creates_nothing(self):
        self.give_free_credit(credits=1)
        emails = [f'r{i}@example.com' for i in range(FREE_REVIEWERS_PER_CYCLE + 1)]
        response = self.api.post('/api/v1/cycles/', {
            'reviewee': str(self.reviewee.uuid),
            'questionnaire': str(self.questionnaire.uuid),
            'reviewer_emails': {'peer': emails},
            'send_invitations': False,
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn(LIMIT_TEXT, str(response.data))
        self.assertEqual(self.cycles(), 0)
        self.assertEqual(ReviewerToken.objects.filter(cycle__reviewee__organization=self.org).count(), 0)
        self.assertEqual(cycle_credits(self.org), 1)


class ClaimLinkLimitTests(ReviewerLimitBase):
    def claim(self, cycle):
        return self.client.get(
            reverse('reviews:claim_token', args=[cycle.invitation_token_peer]), {'force_claim': '1'})

    def test_full_cycle_creates_no_token_and_tells_the_visitor(self):
        self.give_free_credit()
        cycle = self.new_cycle()
        self.add(cycle, FREE_REVIEWERS_PER_CYCLE, reviewer_email='taken@example.com')
        response = self.claim(cycle)
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'This feedback round has reached its maximum number of reviewers.',
                            status_code=404)
        self.assertEqual(cycle.tokens.count(), FREE_REVIEWERS_PER_CYCLE)

    def test_full_cycle_still_lets_an_unassigned_token_be_claimed(self):
        self.give_free_credit()
        cycle = self.new_cycle()
        self.add(cycle, FREE_REVIEWERS_PER_CYCLE)
        response = self.claim(cycle)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(cycle.tokens.filter(claimed_at__isnull=False).count(), 1)
        self.assertEqual(cycle.tokens.count(), FREE_REVIEWERS_PER_CYCLE)
