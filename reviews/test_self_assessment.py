"""One self-assessment token per cycle, addressed to the reviewee."""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization
from core.upgrade_steps import drop_orphan_self_tokens
from questionnaires.models import Questionnaire
from reviews.factories import ResponseFactory
from reviews.models import ReviewCycle, ReviewerToken
from reviews.services import (
    send_reminder_emails,
    send_reviewee_notifications,
    send_reviewer_invitations,
)

SEND_MAIL = 'reviews.services.send_email'


class SelfAssessmentTestCase(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')

        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

        self.reviewee = Reviewee.objects.create(
            organization=self.org, name='Dana Doe', email='Dana@acme.example')
        self.cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=Questionnaire.objects.create(name='Skills', organization=self.org),
        )

    def self_tokens(self):
        return self.cycle.tokens.filter(category='self')


class InvitationTests(SelfAssessmentTestCase):
    def test_the_invitation_is_the_reviewees_token(self):
        with patch(SEND_MAIL) as send:
            send_reviewee_notifications(self.cycle)

        [token] = self.self_tokens()
        self.assertEqual(token.reviewer_email, 'dana@acme.example')
        self.assertIsNotNone(token.invitation_sent_at)
        [self_mail] = [c.kwargs for c in send.call_args_list if 'self-assessment' in c.kwargs['subject']]
        self.assertEqual(self_mail['recipient_list'], ['dana@acme.example'])
        self.assertIn(f'/feedback/{token.token}/', self_mail['message'])

    def test_the_token_from_the_create_form_is_the_one_sent(self):
        addressed = ReviewerToken.objects.create(
            cycle=self.cycle, category='self', reviewer_email='dana@acme.example')

        with patch(SEND_MAIL):
            send_reviewee_notifications(self.cycle)

        self.assertEqual(list(self.self_tokens()), [addressed])
        addressed.refresh_from_db()
        self.assertIsNotNone(addressed.invitation_sent_at)

    def test_sending_pending_invitations_afterwards_mails_it_once(self):
        ReviewerToken.objects.create(cycle=self.cycle, category='self', reviewer_email='dana@acme.example')

        with patch(SEND_MAIL) as send:
            send_reviewee_notifications(self.cycle)
            send_reviewer_invitations(self.cycle)

        subjects = [c.kwargs['subject'] for c in send.call_args_list]
        self.assertEqual(len([s for s in subjects if 'self-assessment' in s]), 1)

    def test_the_reminder_speaks_to_the_reviewee(self):
        with patch(SEND_MAIL):
            send_reviewee_notifications(self.cycle)

        with patch(SEND_MAIL) as send:
            stats = send_reminder_emails(self.cycle)

        self.assertEqual(stats['sent'], 1)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['recipient_list'], ['dana@acme.example'])
        self.assertIn('Your self-assessment is still open', kwargs['subject'])
        self.assertIn('Your self-assessment is still open.', kwargs['message'])
        self.assertNotIn('Your feedback for', kwargs['message'])


class CreateFormTests(SelfAssessmentTestCase):
    def test_the_form_makes_one_self_token(self):
        """The form fills in the reviewee's address for the self-assessment.
        Outside a transaction on_commit runs at once, as it does in
        production; the reviewee's mails must still come after that token."""
        self.client.force_login(self.admin)

        with patch(SEND_MAIL) as send, \
                patch('django.db.transaction.on_commit', side_effect=lambda func, *args, **kwargs: func()):
            self.client.post(reverse('review_cycle_create'), {
                'creation_mode': 'single',
                'reviewee': self.reviewee.id,
                'questionnaire': self.cycle.questionnaire.id,
                'self_emails': 'dana@acme.example',
                'send_invitations_now': '1',
            })

        created = ReviewCycle.objects.exclude(pk=self.cycle.pk).get()
        [token] = created.tokens.filter(category='self')
        self.assertIsNotNone(token.invitation_sent_at)
        subjects = [c.kwargs['subject'] for c in send.call_args_list]
        self.assertEqual(len([s for s in subjects if 'self-assessment' in s]), 1)


class SelfLinkTests(SelfAssessmentTestCase):
    def claim(self):
        url = reverse('reviews:claim_token', args=[self.cycle.invitation_token_self])
        return self.client.get(url + '?force_claim=1')

    def test_the_link_opens_the_invited_token(self):
        invited = ReviewerToken.objects.create(
            cycle=self.cycle, category='self', reviewer_email='dana@acme.example',
            invitation_sent_at=timezone.now())

        response = self.claim()

        self.assertRedirects(response, reverse('reviews:feedback_form', args=[invited.token]),
                             fetch_redirect_response=False)
        self.assertEqual(list(self.self_tokens()), [invited])

    def test_the_link_makes_the_token_if_there_is_none(self):
        self.claim()

        [token] = self.self_tokens()
        self.assertEqual(token.reviewer_email, 'dana@acme.example')

    def test_a_filled_in_self_assessment_wins(self):
        ReviewerToken.objects.create(cycle=self.cycle, category='self', reviewer_email='dana@acme.example')
        done = ReviewerToken.objects.create(cycle=self.cycle, category='self', completed_at=timezone.now())

        response = self.claim()

        self.assertRedirects(response, reverse('reviews:feedback_form', args=[done.token]),
                             fetch_redirect_response=False)


class ManageInvitationsTests(SelfAssessmentTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_a_second_address_makes_no_second_token(self):
        ReviewerToken.objects.create(cycle=self.cycle, category='self', reviewer_email='dana@acme.example')

        with patch(SEND_MAIL):
            self.client.post(reverse('assign_invitations', args=[self.cycle.uuid]),
                             {'self_emails': 'dana@acme.example', 'peer_emails': 'pat@acme.example'})

        self.assertEqual(self.self_tokens().count(), 1)
        self.assertTrue(self.cycle.tokens.filter(category='peer', reviewer_email='pat@acme.example').exists())

    def test_the_page_shows_the_address_instead_of_the_field(self):
        ReviewerToken.objects.create(cycle=self.cycle, category='self', reviewer_email='dana@acme.example')

        response = self.client.get(reverse('manage_invitations', args=[self.cycle.uuid]))

        self.assertContains(response, 'value="dana@acme.example"')
        self.assertNotContains(response, 'name="self_emails"')

    def test_without_a_token_the_address_is_sent(self):
        with patch(SEND_MAIL) as send:
            self.client.post(reverse('assign_invitations', args=[self.cycle.uuid]),
                             {'self_emails': 'dana@acme.example'})

        [token] = self.self_tokens()
        self.assertIsNotNone(token.invitation_sent_at)
        self.assertEqual(send.call_args.kwargs['recipient_list'], ['dana@acme.example'])


class NewCycleTests(SelfAssessmentTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def new_cycle(self):
        with patch(SEND_MAIL) as send, self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('quick_cycle_create', args=[self.reviewee.uuid]),
                             {'questionnaire_id': self.cycle.questionnaire.id})
        return ReviewCycle.objects.exclude(pk=self.cycle.pk).get(), send

    def test_the_reviewee_gets_the_self_assessment_and_the_links(self):
        created, send = self.new_cycle()

        subjects = {c.kwargs['subject'].split(':')[0] for c in send.call_args_list}
        self.assertEqual(subjects, {'Your self-assessment', 'Your links to share with reviewers'})
        [token] = created.tokens.filter(category='self')
        self.assertIsNotNone(token.invitation_sent_at)

    def test_the_copy_keeps_one_self_token(self):
        ReviewerToken.objects.create(cycle=self.cycle, category='self', reviewer_email='dana@acme.example')
        ReviewerToken.objects.create(cycle=self.cycle, category='self', claimed_at=timezone.now())
        ReviewerToken.objects.create(cycle=self.cycle, category='peer', reviewer_email='pat@acme.example')

        created, send = self.new_cycle()

        self.assertEqual(created.tokens.filter(category='self').count(), 1)
        recipients = [address.lower() for c in send.call_args_list for address in c.kwargs['recipient_list']]
        self.assertEqual(recipients.count('dana@acme.example'), 2)
        self.assertIn('pat@acme.example', recipients)


class DropOrphanSelfTokensTests(SelfAssessmentTestCase):
    def addressed(self, **fields):
        return ReviewerToken.objects.create(
            cycle=self.cycle, category='self', reviewer_email='dana@acme.example', **fields)

    def run_step(self):
        drop_orphan_self_tokens(StringIO())

    def test_the_addressed_token_goes_when_the_link_was_used(self):
        orphan = self.addressed()
        used = ReviewerToken.objects.create(
            cycle=self.cycle, category='self', claimed_at=timezone.now(), completed_at=timezone.now())

        self.run_step()

        self.assertEqual(list(self.self_tokens()), [used])
        self.assertFalse(ReviewerToken.objects.filter(pk=orphan.pk).exists())

    def test_a_later_addressed_token_goes(self):
        first = self.addressed()
        self.addressed()

        self.run_step()

        self.assertEqual(list(self.self_tokens()), [first])

    def test_the_only_self_token_stays(self):
        only = self.addressed()

        self.run_step()

        self.assertEqual(list(self.self_tokens()), [only])

    def test_a_token_with_answers_stays(self):
        answered = self.addressed()
        ResponseFactory(cycle=self.cycle, token=answered)
        ReviewerToken.objects.create(cycle=self.cycle, category='self', claimed_at=timezone.now())

        self.run_step()

        self.assertEqual(self.self_tokens().count(), 2)

    def test_a_sent_token_stays(self):
        sent = self.addressed(invitation_sent_at=timezone.now())
        ReviewerToken.objects.create(cycle=self.cycle, category='self', claimed_at=timezone.now())

        self.run_step()

        self.assertTrue(ReviewerToken.objects.filter(pk=sent.pk).exists())
