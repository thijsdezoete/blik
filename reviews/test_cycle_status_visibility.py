import re
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory, UserProfileFactory
from accounts.models import Reviewee
from accounts.permissions import assign_organization_admin, assign_organization_member, set_user_permission
from blik.admin_views import cycle_progress
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory
from reviews.models import ReviewerToken


class CycleStatusVisibilityTests(TestCase):
    def setUp(self):
        self.admin = UserProfileFactory().user
        self.org = self.admin.profile.organization
        self.org.min_responses_for_anonymity = 3
        self.org.save()
        assign_organization_admin(self.admin)
        self.alex = RevieweeFactory(organization=self.org, name='Alex Morgan', email='alex@acme.example',
                                    department='Product Engineering')
        self.cycle = ReviewCycleFactory(reviewee=self.alex, questionnaire=QuestionnaireFactory(organization=self.org))
        sent = timezone.now()
        self.done = ReviewerToken.objects.create(
            cycle=self.cycle, category='peer', reviewer_email='dana@acme.example',
            invitation_sent_at=sent, claimed_at=sent, completed_at=sent)
        self.open = ReviewerToken.objects.create(
            cycle=self.cycle, category='peer', reviewer_email='eli@acme.example', invitation_sent_at=sent)
        self.url = reverse('review_cycle_detail', args=[self.cycle.uuid])

    def reviewee_user(self):
        user = UserProfileFactory(organization=self.org, user__email='alex@acme.example').user
        assign_organization_member(user)
        return user

    def manager_who_runs_the_cycle(self):
        manager = UserProfileFactory(organization=self.org, user__email='hank@acme.example').user
        assign_organization_member(manager, can_create_cycles_for_others=True)
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=Reviewee.objects.get(email='hank@acme.example'), row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.alex, row=1, col=0)
        return manager

    def hr_user(self):
        user = UserProfileFactory(organization=self.org, user__email='hr@acme.example').user
        assign_organization_member(user)
        set_user_permission(user, 'can_view_all_reports', True)
        return user

    def get(self, user, url=None):
        self.client.force_login(user)
        return self.client.get(url or self.url)

    def row(self, html, token):
        """The table row of one token, with its email taken out."""
        match = re.search(r'<tr[^>]* data-email="%s".*?</tr>' % re.escape(token.reviewer_email), html, re.S)
        self.assertIsNotNone(match)
        return match.group(0).replace(token.reviewer_email, '')

    def assert_no_state_per_reviewer(self, user):
        response = self.get(user)
        html = response.content.decode()

        self.assertIs(response.context['shows_reviewer_status'], False)
        # The completed and the open reviewer give the same row
        self.assertEqual(self.row(html, self.done), self.row(html, self.open))
        self.assertNotIn('In Progress', html)
        self.assertNotIn(reverse('send_individual_reminder', args=[self.cycle.uuid, self.open.pk]), html)

    def test_reviewee_gets_no_state_per_reviewer_on_their_own_cycle(self):
        self.assert_no_state_per_reviewer(self.reviewee_user())

    def test_manager_who_runs_the_cycle_gets_no_state_per_reviewer(self):
        self.assert_no_state_per_reviewer(self.manager_who_runs_the_cycle())

    def test_hr_and_admin_keep_the_state_per_reviewer(self):
        for user in (self.hr_user(), self.admin):
            with self.subTest(user=user.email):
                response = self.get(user)
                html = response.content.decode()

                self.assertIs(response.context['shows_reviewer_status'], True)
                self.assertNotIn('progress', response.context)
                self.assertNotEqual(self.row(html, self.done), self.row(html, self.open))
                self.assertIn(reverse('send_individual_reminder', args=[self.cycle.uuid, self.open.pk]), html)

    def test_reviewee_gets_counts_per_category(self):
        progress = self.get(self.reviewee_user()).context['progress']

        self.assertEqual([{key: value for key, value in row.items() if key != 'label'} for row in progress],
                         cycle_progress(self.cycle))
        self.assertEqual([(row['category'], row['invited'], row['answered']) for row in progress if row['category'] == 'peer'],
                         [('peer', 2, 1)])

    def test_closed_cycle_lists_nobody_for_the_reviewee(self):
        # Closing deletes the places nobody opened, so the people left are those who started
        self.cycle.status = 'completed'
        self.cycle.save()

        response = self.get(self.reviewee_user())
        html = response.content.decode()

        self.assertEqual([{key: value for key, value in row.items() if key != 'label'} for row in response.context['progress']],
                         cycle_progress(self.cycle))
        self.assertNotIn('dana@acme.example', html)
        self.assertNotIn('eli@acme.example', html)
        self.assertIn('dana@acme.example', self.get(self.admin).content.decode())

    def test_invitations_page_gives_the_reviewee_no_state_per_reviewer(self):
        response = self.get(self.reviewee_user(), reverse('manage_invitations', args=[self.cycle.uuid]))
        html = response.content.decode()

        self.assertIs(response.context['shows_reviewer_status'], False)
        self.assertEqual(self.row(html, self.done), self.row(html, self.open))
        self.assertNotIn('In Progress', html)

    def test_reminder_for_one_person_is_refused_for_the_reviewee(self):
        for user in (self.reviewee_user(), self.manager_who_runs_the_cycle()):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.post(reverse('send_individual_reminder', args=[self.cycle.uuid, self.open.pk]))

                self.assertEqual(response.status_code, 404)
                self.open.refresh_from_db()
                self.assertIsNone(self.open.reminder_queued_at)

    def test_reviewee_can_remind_everyone_who_has_not_answered(self):
        self.client.force_login(self.reviewee_user())

        # A posted choice of people is not looked at
        response = self.client.post(reverse('send_reminder', args=[self.cycle.uuid]),
                                    {'emails': 'dana@acme.example', 'token_id': self.done.pk}, follow=True)

        self.open.refresh_from_db()
        self.done.refresh_from_db()
        self.assertIsNotNone(self.open.reminder_queued_at)
        self.assertIsNone(self.done.reminder_queued_at)
        texts = ' '.join(str(message) for message in response.context['messages'])
        self.assertNotIn('eli@acme.example', texts)
        self.assertNotIn('dana@acme.example', texts)

    def test_reminder_form_gives_the_reviewee_the_number_and_no_names(self):
        self.three_peers()
        url = reverse('send_reminder_form', args=[self.cycle.uuid])

        response = self.get(self.reviewee_user(), url)
        html = response.content.decode()
        self.assertEqual(response.context['pending_count'], self.cycle.tokens.filter(completed_at__isnull=True).count())
        self.assertNotIn('pending_tokens', response.context)
        self.assertNotIn(str(self.open.token), html)
        self.assertNotIn('eli@acme.example', html)

        self.assertEqual(list(self.get(self.admin, url).context['pending_tokens']),
                         list(self.cycle.tokens.filter(completed_at__isnull=True).order_by('category')))

    def test_remind_all_tells_the_reviewee_how_many_reminders_go_out(self):
        self.client.force_login(self.reviewee_user())

        response = self.client.post(reverse('send_reminder', args=[self.cycle.uuid]), follow=True)

        queued = self.cycle.tokens.filter(reminder_queued_at__isnull=False).count()
        self.assertGreater(queued, 0)
        texts = [str(m) for m in response.context['messages']]
        self.assertEqual(len(texts), 1)
        self.assertIn(str(queued), texts[0])

    def three_peers(self):
        """One never invited, one invited, one with an address and no invitation yet."""
        sent = timezone.now()
        return [ReviewerToken.objects.create(cycle=self.cycle, category='peer', reviewer_email=email,
                                             invitation_sent_at=sent if email == 'gus@acme.example' else None)
                for email in ('fay@acme.example', 'gus@acme.example', 'ivy@acme.example')]

    def counts_page(self, user, tokens):
        """The cycle page, without the emails of `tokens` and without the per-request CSRF values."""
        html = self.get(user).content.decode()
        for token in tokens:
            html = html.replace(token.reviewer_email, '')
        return re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', '', html)

    def test_rows_of_the_counts_view_differ_only_in_email_and_category(self):
        tokens = self.three_peers()
        user = self.reviewee_user()
        open_page = self.counts_page(user, tokens)

        pages = []
        for answered in tokens:
            ReviewerToken.objects.filter(pk__in=[t.pk for t in tokens]).update(completed_at=None, claimed_at=None)
            ReviewerToken.objects.filter(pk=answered.pk).update(completed_at=timezone.now(), claimed_at=timezone.now())
            html = self.get(user).content.decode()
            self.assertEqual(len({self.row(html, token) for token in tokens}), 1)
            pages.append(self.counts_page(user, tokens))

        # Whichever of the three answered, the page is the same
        self.assertEqual(pages[0], pages[1])
        self.assertEqual(pages[0], pages[2])
        # The list and its actions carry no number that moves with an answer;
        # only the counts of cycle_progress, above the list, do
        part = lambda html: html[html.index('<!-- Reviewer Response Status -->'):html.index('<!-- Confirmation Modal -->')]
        self.assertEqual(part(pages[0]), part(open_page))

    def test_send_invitation_for_one_person_is_refused_for_the_reviewee(self):
        never_invited = self.three_peers()[0]
        self.client.force_login(self.reviewee_user())

        response = self.client.post(reverse('send_invitations', args=[self.cycle.uuid]), {'token_id': never_invited.pk})

        self.assertEqual(response.status_code, 404)
        never_invited.refresh_from_db()
        self.assertIsNone(never_invited.invitation_queued_at)

    def test_send_all_invitations_gives_the_reviewee_the_same_message_whatever_was_sent(self):
        never_invited = self.three_peers()[0]
        self.client.force_login(self.reviewee_user())
        url = reverse('send_invitations', args=[self.cycle.uuid])

        def message():
            response = self.client.post(url, follow=True)
            return [str(m) for m in response.context['messages']]

        with_pending = message()
        never_invited.refresh_from_db()
        self.assertIsNotNone(never_invited.invitation_queued_at)
        ReviewerToken.objects.filter(cycle=self.cycle).update(invitation_sent_at=timezone.now())
        without_pending = message()

        self.assertEqual(with_pending, without_pending)
        self.assertEqual(len(with_pending), 1)
        self.assertFalse(re.search(r'\d', with_pending[0]))

    def test_invitations_page_keeps_the_creation_order(self):
        tokens = self.three_peers()
        start = timezone.now() - timedelta(days=1)
        # Created in another order than their ids, so the order cannot come from the row ids
        for n, token in enumerate([self.done, self.open, *reversed(tokens)]):
            ReviewerToken.objects.filter(pk=token.pk).update(created_at=start + timedelta(minutes=n))
        ReviewerToken.objects.filter(pk=tokens[0].pk).update(completed_at=timezone.now())

        html = self.get(self.reviewee_user(), reverse('manage_invitations', args=[self.cycle.uuid])).content.decode()

        emails = re.findall(r'<tr[^>]* data-email="([^"]+)"', html)
        self.assertEqual(emails, ['dana@acme.example', 'eli@acme.example',
                                  'ivy@acme.example', 'gus@acme.example', 'fay@acme.example'])
