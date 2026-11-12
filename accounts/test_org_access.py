"""Managers read the reports of their direct reports in the org chart."""
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from accounts.factories import UserProfileFactory
from accounts.models import Reviewee
from accounts.org_import import import_org_chart, rows_from_csv
from accounts.permissions import (
    assign_organization_member,
    ensure_permission_groups,
    direct_report_emails,
    managers_without_account,
)
from core.factories import OrganizationFactory, UserFactory
from reviews.factories import ReviewCycleFactory

CSV = """name,email,department,manager_email
Prof Ada,ada@uni.example,Chair,
Hank Head,hank@uni.example,Optics,ada@uni.example
Hilde Head,hilde@uni.example,Lasers,ada@uni.example
Sam Staff,sam@uni.example,Optics,hank@uni.example
Sue Staff,sue@uni.example,Optics,hank@uni.example
Lea Laser,lea@uni.example,Lasers,hilde@uni.example
"""


class OrgAccessTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = OrganizationFactory()
        import_org_chart(self.org, rows_from_csv(CSV)[0])
        self.cycles = {
            r.email: ReviewCycleFactory(reviewee=r) for r in Reviewee.objects.filter(organization=self.org)
        }

    def _login(self, email):
        user = UserFactory(username=email.split('@')[0], email=email)
        UserProfileFactory(user=user, organization=self.org)
        assign_organization_member(user)
        self.client.force_login(user)
        return user

    def test_direct_reports_only_not_the_layers_below(self):
        ada, hank, sam = (UserFactory(username=n, email=f'{n}@uni.example') for n in ('ada', 'hank', 'sam'))

        self.assertEqual(
            direct_report_emails(ada, self.org),
            {'hank@uni.example', 'hilde@uni.example'},
        )
        self.assertEqual(direct_report_emails(hank, self.org), {'sam@uni.example', 'sue@uni.example'})
        self.assertEqual(direct_report_emails(sam, self.org), set())
        self.assertEqual(direct_report_emails(ada, OrganizationFactory()), set())

    def test_a_head_reads_the_reports_of_their_own_staff_only(self):
        self._login('hank@uni.example')

        ok = self.client.get(reverse('reports:view_report', args=[self.cycles['sam@uni.example'].uuid]))
        other_unit = self.client.get(reverse('reports:view_report', args=[self.cycles['lea@uni.example'].uuid]))
        boss = self.client.get(reverse('reports:view_report', args=[self.cycles['ada@uni.example'].uuid]))

        self.assertEqual(ok.status_code, 200)
        self.assertNotContains(ok, reverse('reports:regenerate_report', args=[self.cycles['sam@uni.example'].uuid]))
        self.assertEqual(other_unit.status_code, 404)
        self.assertEqual(boss.status_code, 404)

    def test_a_manager_cannot_run_the_cycles_below_them(self):
        self._login('hank@uni.example')
        sam_cycle = self.cycles['sam@uni.example']

        self.assertEqual(self.client.get(reverse('review_cycle_detail', args=[sam_cycle.uuid])).status_code, 404)
        self.assertEqual(self.client.get(reverse('reports:regenerate_report', args=[sam_cycle.uuid])).status_code, 404)

    def test_the_cycle_list_offers_only_the_report_for_cycles_below(self):
        self._login('hank@uni.example')

        response = self.client.get(reverse('review_cycle_list'))

        listed = {c.reviewee.email: c.report_only for c in response.context['cycles']}
        self.assertEqual(listed, {'hank@uni.example': False, 'sam@uni.example': True, 'sue@uni.example': True})
        self.assertContains(response, reverse('reports:view_report', args=[self.cycles['sam@uni.example'].uuid]))


    def test_the_reviewee_list_shows_a_manager_only_themselves_and_their_direct_reports(self):
        self._login('hank@uni.example')

        response = self.client.get(reverse('reviewee_list'))

        listed = {item['reviewee'].email for item in response.context['reviewees_with_latest']}
        self.assertEqual(listed, {'hank@uni.example', 'sam@uni.example', 'sue@uni.example'})

    def test_managers_without_account_lists_who_cannot_log_in(self):
        from accounts.factories import OrganizationInvitationFactory
        self._login('hank@uni.example')  # has an account now
        OrganizationInvitationFactory(organization=self.org, email='Hilde@uni.example')

        found = {m.email: m.invited for m in managers_without_account(self.org)}

        # Sam, Sue and Lea manage nobody; Hank has an account.
        self.assertEqual(found, {'ada@uni.example': False, 'hilde@uni.example': True})

    def test_invite_managers_queues_the_message_for_the_selected_who_are_not_yet_invited(self):
        from unittest.mock import patch
        from accounts.factories import OrganizationInvitationFactory
        from accounts.models import OrganizationInvitation
        from accounts.permissions import assign_organization_admin
        from reviews.outbox import send_queued_emails
        assign_organization_admin(self._login('hank@uni.example'))
        OrganizationInvitationFactory(organization=self.org, email='hilde@uni.example')

        Reviewee.objects.filter(email='ada@uni.example').update(language='de')
        sent_in = []
        with patch('core.email.send_email', side_effect=lambda **kw: sent_in.append(translation.get_language())) as send:
            self.client.post(reverse('invite_managers'), {
                'message': 'Read the reports of your staff.',
                # Hilde is invited already; Sam manages nobody; an outsider is not in the chart.
                'emails': ['Ada@uni.example', 'hilde@uni.example', 'sam@uni.example', 'x@other.example'],
            })
            send.assert_not_called()  # the request only queues
            queued = OrganizationInvitation.objects.get(email_queued_at__isnull=False)
            self.assertEqual(queued.email, 'ada@uni.example')

            stats = send_queued_emails()

        (call,) = send.call_args_list
        self.assertEqual(call.kwargs['recipient_list'], ['ada@uni.example'])
        self.assertIn('Read the reports of your staff.', call.kwargs['message'])
        self.assertIn('Read the reports of your staff.', call.kwargs['html_message'])
        self.assertIn(queued.token, call.kwargs['message'])
        self.assertEqual(stats['sent'], 1)
        self.assertEqual(sent_in, ['de'])  # Ada's own language, not the organization's
        queued.refresh_from_db()
        self.assertIsNone(queued.email_queued_at)

    def test_an_invitation_that_cannot_be_sent_is_not_kept(self):
        from unittest.mock import patch
        from accounts.models import OrganizationInvitation
        from accounts.permissions import assign_organization_admin
        assign_organization_admin(self._login('hank@uni.example'))

        with patch('accounts.invitation_views.send_email', side_effect=OSError('no smtp')):
            self.client.post(reverse('send_invitation'), {'email': 'new@uni.example'})

        self.assertFalse(OrganizationInvitation.objects.filter(organization=self.org).exists())

    def test_an_expired_invitation_is_made_new(self):
        from datetime import timedelta
        from unittest.mock import patch
        from django.utils import timezone
        from accounts.factories import OrganizationInvitationFactory
        from accounts.permissions import assign_organization_admin
        assign_organization_admin(self._login('hank@uni.example'))
        old = OrganizationInvitationFactory(
            organization=self.org, email='new@uni.example', expires_at=timezone.now() - timedelta(days=1))
        old_token = old.token

        with patch('accounts.invitation_views.send_email'):
            self.client.post(reverse('send_invitation'), {'email': 'new@uni.example'})

        old.refresh_from_db()
        self.assertTrue(old.is_valid())
        self.assertNotEqual(old.token, old_token)
