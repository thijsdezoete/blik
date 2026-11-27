"""An email that is added to a running review gets a free place, never one that someone took through an invite link."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.factories import UserProfileFactory
from accounts.permissions import assign_organization_admin
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.services import assign_tokens_to_emails


class TakenPlaceTests(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        assign_organization_admin(self.profile.user)
        self.client.force_login(self.profile.user)
        self.cycle = ReviewCycleFactory(reviewee__organization=self.profile.organization)
        self.claimed = ReviewerTokenFactory(cycle=self.cycle, category='peer', claimed_at=timezone.now())
        self.answered = ReviewerTokenFactory(
            cycle=self.cycle, category='peer', claimed_at=timezone.now(), completed_at=timezone.now())

    def taken_emails(self):
        self.claimed.refresh_from_db()
        self.answered.refresh_from_db()
        return self.claimed.reviewer_email, self.answered.reviewer_email

    def test_an_email_goes_to_the_free_place(self):
        free = ReviewerTokenFactory(cycle=self.cycle, category='peer')

        stats = assign_tokens_to_emails(self.cycle, {'peer': ['kim@acme.example']})

        free.refresh_from_db()
        self.assertEqual(free.reviewer_email, 'kim@acme.example')
        self.assertEqual(self.taken_emails(), (None, None))
        self.assertEqual(stats['assigned'], 1)

    def test_without_a_free_place_no_email_is_assigned(self):
        stats = assign_tokens_to_emails(self.cycle, {'peer': ['kim@acme.example']})

        self.assertEqual(self.taken_emails(), (None, None))
        self.assertEqual(stats['assigned'], 0)
        self.assertEqual(len(stats['errors']), 1)

    def test_the_invitations_page_makes_a_new_place_for_the_email(self):
        self.client.post(reverse('assign_invitations', args=[self.cycle.uuid]), {'peer_emails': 'kim@acme.example'})

        self.assertEqual(self.taken_emails(), (None, None))
        self.assertEqual(
            list(self.cycle.tokens.filter(reviewer_email='kim@acme.example').values_list('claimed_at', 'completed_at')),
            [(None, None)])
