"""Managers read the reports of everyone below them in the org chart."""
from django.test import TestCase
from django.urls import reverse

from accounts.factories import UserProfileFactory
from accounts.models import Reviewee
from accounts.org_import import import_org_chart, rows_from_csv
from accounts.permissions import (
    assign_organization_member,
    ensure_permission_groups,
    reviewee_emails_below,
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

    def test_everyone_below_over_all_layers(self):
        ada, hank, sam = (UserFactory(username=n, email=f'{n}@uni.example') for n in ('ada', 'hank', 'sam'))

        self.assertEqual(
            reviewee_emails_below(ada, self.org),
            {'hank@uni.example', 'hilde@uni.example', 'sam@uni.example', 'sue@uni.example', 'lea@uni.example'},
        )
        self.assertEqual(reviewee_emails_below(hank, self.org), {'sam@uni.example', 'sue@uni.example'})
        self.assertEqual(reviewee_emails_below(sam, self.org), set())
        self.assertEqual(reviewee_emails_below(ada, OrganizationFactory()), set())

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

