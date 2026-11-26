import re

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

        html = self.get(self.reviewee_user()).content.decode()

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

    def test_reminder_form_gives_the_reviewee_a_number_and_no_names(self):
        url = reverse('send_reminder_form', args=[self.cycle.uuid])
        response = self.get(self.reviewee_user(), url)
        html = response.content.decode()

        self.assertNotIn('pending_tokens', response.context)
        self.assertEqual(response.context['reminder_count'], 1)
        self.assertNotIn(str(self.open.token), html)
        self.assertNotIn('eli@acme.example', html)

        self.assertEqual(list(self.get(self.admin, url).context['pending_tokens']), [self.open])
