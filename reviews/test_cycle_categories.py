"""Choosing which feedback categories a cycle collects.

Before these flags every cycle collected all four categories: the form had
no say, the invitation mail listed every link, and the detail page showed
them all. Existing cycles keep collecting all four (the fields default to
True), so nothing changes for them.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization
from questionnaires.models import Questionnaire
from reviews.models import CATEGORY_ORDER, ReviewCycle, ReviewerToken

SEND_MAIL = 'reviews.services.send_email'


class CycleCategoryTestCase(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')

        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

        self.reviewee = Reviewee.objects.create(
            organization=self.org, name='Dana Doe', email='dana@acme.example')
        self.questionnaire = Questionnaire.objects.create(
            name='Professional Skills', organization=self.org)

        self.client.force_login(self.admin)

    def _create_cycle_via_form(self, **extra):
        data = {
            'creation_mode': 'single',
            'reviewee': self.reviewee.id,
            'questionnaire': self.questionnaire.id,
        }
        data.update(extra)
        return self.client.post(reverse('review_cycle_create'), data)


class ModelDefaultTests(CycleCategoryTestCase):
    def test_a_cycle_collects_everything_unless_told_otherwise(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire)

        self.assertEqual(cycle.active_categories, list(CATEGORY_ORDER))

    def test_active_categories_keeps_report_order(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_peer=False)

        self.assertEqual(cycle.active_categories, ['self', 'manager', 'direct_report'])

    def test_collects_answers_per_category(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_direct_report=False)

        self.assertTrue(cycle.collects('manager'))
        self.assertFalse(cycle.collects('direct_report'))


class CreationFromTheFormTests(CycleCategoryTestCase):
    def test_selected_categories_are_stored(self):
        self._create_cycle_via_form(
            categories_submitted='1', include_self='on', include_manager='on')

        cycle = ReviewCycle.objects.get(reviewee=self.reviewee)
        self.assertEqual(cycle.active_categories, ['self', 'manager'])

    def test_a_cycle_without_any_category_is_refused(self):
        response = self._create_cycle_via_form(categories_submitted='1')

        self.assertFalse(ReviewCycle.objects.filter(reviewee=self.reviewee).exists())
        self.assertRedirects(response, reverse('review_cycle_create'))

    def test_a_client_that_sends_no_categories_still_gets_all_four(self):
        """Without the marker the post predates the checkboxes — old behaviour."""
        self._create_cycle_via_form()

        cycle = ReviewCycle.objects.get(reviewee=self.reviewee)
        self.assertEqual(cycle.active_categories, list(CATEGORY_ORDER))

    def test_emails_for_a_dropped_category_are_ignored(self):
        self._create_cycle_via_form(
            categories_submitted='1',
            include_self='on',
            self_emails='dana@acme.example',
            peer_emails='peer@acme.example',
        )

        cycle = ReviewCycle.objects.get(reviewee=self.reviewee)
        self.assertEqual(cycle.tokens.filter(category='peer').count(), 0)
        self.assertEqual(cycle.tokens.filter(category='self').count(), 1)

    def test_bulk_creation_applies_the_same_categories(self):
        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'questionnaire': self.questionnaire.id,
            'categories_submitted': '1',
            'include_peer': 'on',
        })

        for cycle in ReviewCycle.objects.all():
            self.assertEqual(cycle.active_categories, ['peer'])


class QuickCycleTests(CycleCategoryTestCase):
    def test_it_carries_the_categories_of_the_cycle_it_copies(self):
        previous = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_self=False, include_direct_report=False)

        self.client.post(
            reverse('quick_cycle_create', args=[self.reviewee.uuid]),
            {'questionnaire_id': self.questionnaire.id},
        )

        created = ReviewCycle.objects.exclude(pk=previous.pk).get()
        self.assertEqual(created.active_categories, ['peer', 'manager'])

    def test_without_a_previous_cycle_it_collects_everything(self):
        self.client.post(
            reverse('quick_cycle_create', args=[self.reviewee.uuid]),
            {'questionnaire_id': self.questionnaire.id},
        )

        created = ReviewCycle.objects.get()
        self.assertEqual(created.active_categories, list(CATEGORY_ORDER))

    def test_no_tokens_are_made_for_a_dropped_category(self):
        previous = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_peer=False)

        self.client.post(
            reverse('quick_cycle_create', args=[self.reviewee.uuid]),
            {'questionnaire_id': self.questionnaire.id},
        )

        created = ReviewCycle.objects.exclude(pk=previous.pk).get()
        self.assertEqual(created.tokens.filter(category='peer').count(), 0)

    def test_the_dialog_chooses_the_categories(self):
        previous = ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)

        self.client.post(
            reverse('quick_cycle_create', args=[self.reviewee.uuid]),
            {'questionnaire_id': self.questionnaire.id, 'categories_submitted': '1',
             'include_self': 'on', 'include_manager': 'on'},
        )

        created = ReviewCycle.objects.exclude(pk=previous.pk).get()
        self.assertEqual(created.active_categories, ['self', 'manager'])

    def test_the_dialog_needs_a_category(self):
        self.client.post(
            reverse('quick_cycle_create', args=[self.reviewee.uuid]),
            {'questionnaire_id': self.questionnaire.id, 'categories_submitted': '1'},
        )

        self.assertFalse(ReviewCycle.objects.exists())

    def test_reviewers_of_a_category_cleared_in_the_dialog_are_not_copied(self):
        previous = ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)
        ReviewerToken.objects.create(cycle=previous, category='peer', reviewer_email='pat@acme.example')

        with patch(SEND_MAIL) as send:
            self.client.post(
                reverse('quick_cycle_create', args=[self.reviewee.uuid]),
                {'questionnaire_id': self.questionnaire.id, 'categories_submitted': '1',
                 'include_manager': 'on'},
            )

        created = ReviewCycle.objects.exclude(pk=previous.pk).get()
        self.assertFalse(created.tokens.filter(category='peer').exists())
        send.assert_not_called()


class StartDialogTests(CycleCategoryTestCase):
    """"New Cycle" asks before it creates a cycle and sends its mails."""

    def setUp(self):
        super().setUp()
        self.previous = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire, include_peer=False)

    def test_the_cycle_list_opens_a_dialog_per_row(self):
        response = self.client.get(reverse('review_cycle_list'))

        self.assertContains(response, f'data-reviewee-dialog="start-review-{self.previous.uuid}"')
        self.assertContains(response, f'id="start-review-{self.previous.uuid}"')
        self.assertContains(response, f'name="source_cycle_uuid" value="{self.previous.uuid}"')
        self.assertNotContains(response, 'dropdown-menu')

    def test_the_dialog_starts_from_the_categories_of_the_previous_cycle(self):
        for url in (reverse('review_cycle_list'), reverse('reviewee_list')):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertContains(response, 'name="include_self" checked>')
                self.assertContains(response, 'name="include_peer">')


class InvitationMailTests(CycleCategoryTestCase):
    def _send(self, cycle):
        from reviews.services import send_reviewee_notifications
        with patch(SEND_MAIL) as send:
            send_reviewee_notifications(cycle)
        return send

    def test_self_only_cycle_sends_no_link_mail(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_peer=False, include_manager=False, include_direct_report=False)

        send = self._send(cycle)

        self.assertEqual(send.call_count, 1)
        self.assertIn('self-assessment', send.call_args_list[0].kwargs['subject'])

    def test_cycle_without_self_sends_no_self_mail(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_self=False)

        send = self._send(cycle)

        self.assertEqual(send.call_count, 1)
        self.assertIn('Your links to share with reviewers',
                      send.call_args_list[0].kwargs['subject'])

    def test_the_link_mail_only_lists_the_active_categories(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_self=False, include_direct_report=False)

        send = self._send(cycle)
        body = send.call_args_list[0].kwargs['html_message']

        self.assertIn(str(cycle.invitation_token_peer), body)
        self.assertIn(str(cycle.invitation_token_manager), body)
        self.assertNotIn(str(cycle.invitation_token_direct_report), body)


class ResendLinksTests(CycleCategoryTestCase):
    """The cycle page sends the reviewee the links to share once more."""

    def resend(self, cycle):
        with patch(SEND_MAIL) as send:
            response = self.client.post(reverse('send_reviewee_links', args=[cycle.uuid]))
        return response, send

    def test_the_reviewee_gets_the_links_of_the_active_categories(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire, include_direct_report=False)

        response, send = self.resend(cycle)

        self.assertRedirects(response, reverse('review_cycle_detail', args=[cycle.uuid]),
                             fetch_redirect_response=False)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['recipient_list'], ['dana@acme.example'])
        self.assertIn('Your links to share with reviewers', kwargs['subject'])
        self.assertIn(str(cycle.invitation_token_peer), kwargs['html_message'])
        self.assertNotIn(str(cycle.invitation_token_direct_report), kwargs['html_message'])
        self.assertNotIn(str(cycle.invitation_token_self), kwargs['html_message'])

    def test_it_takes_a_post(self):
        cycle = ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)

        response = self.client.get(reverse('send_reviewee_links', args=[cycle.uuid]))

        self.assertEqual(response.status_code, 405)

    def test_nothing_goes_out_without_links_that_work(self):
        closed = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire, status='completed')
        self_only = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_peer=False, include_manager=False, include_direct_report=False)

        for cycle in (closed, self_only):
            with self.subTest(status=cycle.status, categories=cycle.active_categories):
                send = self.resend(cycle)[1]
                send.assert_not_called()

    def test_another_organization_cannot_send(self):
        cycle = ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)
        other_org = Organization.objects.create(name='Other', email='org@other.example')
        outsider = User.objects.create_user(username='outsider', email='admin@other.example', password='pw')
        UserProfile.objects.create(user=outsider, organization=other_org)
        assign_organization_admin(outsider)
        self.client.force_login(outsider)

        response, send = self.resend(cycle)

        self.assertEqual(response.status_code, 404)
        send.assert_not_called()

    def test_the_cycle_page_offers_the_button(self):
        cycle = ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)

        response = self.client.get(reverse('review_cycle_detail', args=[cycle.uuid]))

        self.assertContains(response, reverse('send_reviewee_links', args=[cycle.uuid]))


class InvitationLinkTests(CycleCategoryTestCase):
    def test_a_link_for_a_dropped_category_is_refused(self):
        """Links live in old mails; dropping a category must close them."""
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_peer=False)

        response = self.client.get(
            reverse('reviews:claim_token',
                    kwargs={'invitation_token': cycle.invitation_token_peer}),
            {'force_claim': '1'},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ReviewerToken.objects.filter(category='peer').count(), 0)

    def test_a_link_for_an_active_category_still_works(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_peer=False)

        response = self.client.get(
            reverse('reviews:claim_token',
                    kwargs={'invitation_token': cycle.invitation_token_manager}),
            {'force_claim': '1'},
        )

        self.assertNotEqual(response.status_code, 404)


class DetailPageTests(CycleCategoryTestCase):
    def test_only_active_categories_offer_an_invitation_link(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_direct_report=False)

        response = self.client.get(
            reverse('review_cycle_detail', kwargs={'cycle_uuid': cycle.uuid}))

        self.assertContains(response, str(cycle.invitation_token_peer))
        self.assertNotContains(response, str(cycle.invitation_token_direct_report))


class ApiTests(CycleCategoryTestCase):
    """The REST API must not be a way around the cycle's categories."""

    def setUp(self):
        super().setUp()
        from api.models import APIToken
        from rest_framework.test import APIClient

        token = APIToken.objects.create(
            organization=self.org, name='test', created_by=self.admin)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.token}')

    def test_a_cycle_reports_the_categories_it_collects(self):
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_peer=False)

        response = self.client.get(f'/api/v1/cycles/{cycle.uuid}/')

        self.assertEqual(response.json()['categories'],
                         ['self', 'manager', 'direct_report'])

    def test_categories_can_be_set_when_creating_a_cycle(self):
        response = self.client.post(
            '/api/v1/cycles/',
            {
                'reviewee': str(self.reviewee.uuid),
                'questionnaire': str(self.questionnaire.uuid),
                'include_peer': False,
                'include_direct_report': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        cycle = ReviewCycle.objects.get(uuid=response.json()['uuid'])
        self.assertEqual(cycle.active_categories, ['self', 'manager'])

    def test_emails_for_a_dropped_category_create_no_tokens(self):
        response = self.client.post(
            '/api/v1/cycles/',
            {
                'reviewee': str(self.reviewee.uuid),
                'questionnaire': str(self.questionnaire.uuid),
                'include_peer': False,
                'reviewer_emails': {'peer': ['peer@acme.example'],
                                    'manager': ['boss@acme.example']},
                'send_invitations': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        cycle = ReviewCycle.objects.get(uuid=response.json()['uuid'])
        self.assertEqual(cycle.tokens.filter(category='peer').count(), 0)
        self.assertEqual(cycle.tokens.filter(category='manager').count(), 1)


class ManageInvitationsTests(CycleCategoryTestCase):
    """The invitations page must offer the cycle's categories, and only those."""

    def setUp(self):
        super().setUp()
        self.cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee, questionnaire=self.questionnaire,
            include_peer=False, include_direct_report=False)

    def _page(self):
        return self.client.get(
            reverse('manage_invitations', kwargs={'cycle_uuid': self.cycle.uuid}))

    def _assign(self, **emails):
        return self.client.post(
            reverse('assign_invitations', kwargs={'cycle_uuid': self.cycle.uuid}),
            emails,
        )

    def test_the_form_only_offers_the_active_categories(self):
        response = self._page()

        self.assertContains(response, 'name="self_emails"')
        self.assertContains(response, 'name="manager_emails"')
        self.assertNotContains(response, 'name="peer_emails"')
        self.assertNotContains(response, 'name="direct_report_emails"')

    def test_a_posted_email_for_a_dropped_category_is_ignored(self):
        self._assign(peer_emails='peer@acme.example',
                     manager_emails='boss@acme.example')

        self.assertEqual(self.cycle.tokens.filter(category='peer').count(), 0)
        self.assertEqual(self.cycle.tokens.filter(category='manager').count(), 1)

    def test_an_existing_token_of_a_dropped_category_gets_no_reviewer(self):
        """Tokens can predate the category being dropped — they stay empty."""
        stale = ReviewerToken.objects.create(cycle=self.cycle, category='peer')

        self._assign(peer_emails='peer@acme.example')

        stale.refresh_from_db()
        self.assertIsNone(stale.reviewer_email)
