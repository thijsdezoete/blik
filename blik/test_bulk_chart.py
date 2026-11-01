"""
Phase 3 tests: chart-driven bulk cycle creation and preview page.
"""
import json

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.factories import (
    RevieweeFactory,
    OrgUnitFactory,
    OrgUnitMembershipFactory,
    UserProfileFactory,
)
from accounts.models import UserProfile
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle, ReviewerToken


NON_HASHING_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _grant_manage(user):
    ct = ContentType.objects.get_for_model(UserProfile)
    perm, _ = Permission.objects.get_or_create(
        codename='can_manage_organization',
        content_type=ct,
        defaults={'name': 'Can manage organization settings'},
    )
    user.user_permissions.add(perm)


@override_settings(STORAGES=NON_HASHING_STORAGES)
class BulkChartDerivationTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory(username='bulk_admin')
        UserProfileFactory(user=self.admin, organization=self.org,
                           can_create_cycles_for_others=True)
        _grant_manage(self.admin)
        self.client.force_login(self.admin)

        self.questionnaire = QuestionnaireFactory(organization=self.org)

    def test_cycle_create_form_hides_chart_option_when_no_units(self):
        """Radio shows 'no units yet' text when the chart is empty."""
        RevieweeFactory(organization=self.org)
        resp = self.client.get(reverse('review_cycle_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'no units yet')

    def test_cycle_create_form_offers_chart_when_units_exist(self):
        RevieweeFactory(organization=self.org)
        OrgUnitFactory(organization=self.org, name='Leadership')
        resp = self.client.get(reverse('review_cycle_create'))
        self.assertContains(resp, 'Derive from org chart')
        self.assertNotContains(resp, 'no units yet')

    def test_bulk_chart_source_creates_tokens_per_reviewee(self):
        # Build a chart: Leadership (CEO, CFO → Alice, Bob)
        ceo = RevieweeFactory(organization=self.org, name='CEO',
                              email='ceo@example.com')
        cfo = RevieweeFactory(organization=self.org, name='CFO',
                              email='cfo@example.com')
        alice = RevieweeFactory(organization=self.org, name='Alice',
                                email='alice@example.com')
        bob = RevieweeFactory(organization=self.org, name='Bob',
                              email='bob@example.com')

        unit = OrgUnitFactory(organization=self.org, name='Leadership')
        OrgUnitMembershipFactory(unit=unit, reviewee=ceo, row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=cfo, row=0, col=1)
        OrgUnitMembershipFactory(unit=unit, reviewee=alice, row=1, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=bob, row=1, col=1)

        resp = self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'bulk_source': 'chart',
            'questionnaire': str(self.questionnaire.id),
        })
        self.assertEqual(resp.status_code, 302)

        # One cycle per active reviewee (may include an auto-created reviewee
        # for the admin user — we don't care about the exact count, only that
        # Alice's and the CEO's cycles have the correct chart-derived emails).
        cycles = ReviewCycle.objects.filter(
            reviewee__organization=self.org,
            questionnaire=self.questionnaire,
        )
        self.assertGreaterEqual(cycles.count(), 4)

        # Alice's cycle should have managers=CEO,CFO and peer=Bob.
        alice_cycle = cycles.get(reviewee=alice)
        manager_emails = set(alice_cycle.tokens.filter(
            category='manager', reviewer_email__isnull=False,
        ).values_list('reviewer_email', flat=True))
        peer_emails = set(alice_cycle.tokens.filter(
            category='peer', reviewer_email__isnull=False,
        ).values_list('reviewer_email', flat=True))
        self.assertEqual(manager_emails, {'ceo@example.com', 'cfo@example.com'})
        self.assertEqual(peer_emails, {'bob@example.com'})

        # CEO's cycle should have direct_reports=Alice,Bob and peer=CFO.
        ceo_cycle = cycles.get(reviewee=ceo)
        dr_emails = set(ceo_cycle.tokens.filter(
            category='direct_report', reviewer_email__isnull=False,
        ).values_list('reviewer_email', flat=True))
        peer_emails = set(ceo_cycle.tokens.filter(
            category='peer', reviewer_email__isnull=False,
        ).values_list('reviewer_email', flat=True))
        self.assertEqual(dr_emails, {'alice@example.com', 'bob@example.com'})
        self.assertEqual(peer_emails, {'cfo@example.com'})

    def test_bulk_empty_source_creates_no_tokens(self):
        RevieweeFactory(organization=self.org, name='A')
        RevieweeFactory(organization=self.org, name='B')
        # Even with a chart in place, 'empty' keeps existing behavior.
        t = OrgUnitFactory(organization=self.org)

        resp = self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'bulk_source': 'empty',
            'questionnaire': str(self.questionnaire.id),
        })
        self.assertEqual(resp.status_code, 302)

        for cycle in ReviewCycle.objects.filter(
                reviewee__organization=self.org):
            self.assertEqual(
                cycle.tokens.filter(reviewer_email__isnull=False).count(), 0)

    def test_unplaced_reviewees_get_only_self_token_in_chart_mode(self):
        """
        A reviewee not on any unit should still get a cycle — with only a
        self-assessment token and no external reviewer tokens.
        """
        on_unit = RevieweeFactory(organization=self.org, name='OnUnit')
        loner = RevieweeFactory(organization=self.org, name='Loner')

        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=on_unit, row=0, col=0)

        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'bulk_source': 'chart',
            'questionnaire': str(self.questionnaire.id),
        })

        loner_cycle = ReviewCycle.objects.get(reviewee=loner)
        non_self_tokens = loner_cycle.tokens.filter(
            reviewer_email__isnull=False,
        ).exclude(category='self')
        self.assertEqual(non_self_tokens.count(), 0)


@override_settings(STORAGES=NON_HASHING_STORAGES)
class BulkPreviewPageTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory(username='preview_admin')
        UserProfileFactory(user=self.admin, organization=self.org,
                           can_create_cycles_for_others=True)
        _grant_manage(self.admin)
        self.client.force_login(self.admin)

        self.questionnaire = QuestionnaireFactory(organization=self.org)

    def test_preview_shows_per_cycle_counts_when_derived(self):
        ceo = RevieweeFactory(organization=self.org, name='CEO',
                              email='ceo@example.com')
        alice = RevieweeFactory(organization=self.org, name='Alice',
                                email='alice@example.com')
        unit = OrgUnitFactory(organization=self.org, name='T')
        OrgUnitMembershipFactory(unit=unit, reviewee=ceo, row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=alice, row=1, col=0)

        # POST creates cycles + redirects to preview
        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'bulk_source': 'chart',
            'questionnaire': str(self.questionnaire.id),
        })

        resp = self.client.get(reverse('bulk_send_invitations'))
        self.assertEqual(resp.status_code, 200)
        # Derived-mode columns appear:
        self.assertContains(resp, 'Direct reports')
        self.assertContains(resp, 'CEO')
        self.assertContains(resp, 'Alice')

    def test_preview_flags_unplaced(self):
        loner = RevieweeFactory(organization=self.org, name='Loner')
        # Ensure at least one unit exists so chart mode can be chosen.
        OrgUnitFactory(organization=self.org, name='OtherUnit')

        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'bulk_source': 'chart',
            'questionnaire': str(self.questionnaire.id),
        })

        resp = self.client.get(reverse('bulk_send_invitations'))
        self.assertContains(resp, 'Unplaced')
        self.assertContains(resp, 'aren')  # "aren't on any org-chart unit yet"

    def test_preview_post_schedules_sends_and_clears_session(self):
        RevieweeFactory(organization=self.org)
        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'bulk_source': 'empty',
            'questionnaire': str(self.questionnaire.id),
        })
        # POST the preview's form
        resp = self.client.post(reverse('bulk_send_invitations'))
        self.assertEqual(resp.status_code, 302)

        # Session keys cleared
        self.assertNotIn('pending_invitation_cycles', self.client.session)
        self.assertNotIn('pending_bulk_source', self.client.session)


@override_settings(STORAGES=NON_HASHING_STORAGES)
class MultiUnitBadgeTests(TestCase):
    """
    The ▣ multi-unit badge should render with a tooltip listing the other
    unit names that the reviewee belongs to.
    """
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory(username='badge_admin')
        UserProfileFactory(user=self.admin, organization=self.org,
                           can_create_cycles_for_others=True)
        _grant_manage(self.admin)
        self.client.force_login(self.admin)

    def test_badge_tooltip_lists_sibling_unit_names(self):
        vp = RevieweeFactory(organization=self.org, name='VP Eng')
        leadership = OrgUnitFactory(organization=self.org, name='Leadership')
        engineering = OrgUnitFactory(organization=self.org, name='Engineering')
        sales = OrgUnitFactory(organization=self.org, name='Sales')
        OrgUnitMembershipFactory(unit=leadership, reviewee=vp, row=1, col=0)
        OrgUnitMembershipFactory(unit=engineering, reviewee=vp, row=0, col=0)
        OrgUnitMembershipFactory(unit=sales, reviewee=vp, row=0, col=0)

        resp = self.client.get(reverse('org_chart'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Looking at the Leadership card, the tooltip should mention
        # Engineering and Sales (not Leadership itself).
        self.assertIn('Also in: Engineering, Sales', html)

    def test_no_badge_when_only_on_one_unit(self):
        r = RevieweeFactory(organization=self.org, name='Solo')
        t = OrgUnitFactory(organization=self.org, name='Solo OrgUnit')
        OrgUnitMembershipFactory(unit=t, reviewee=r, row=0, col=0)

        resp = self.client.get(reverse('org_chart'))
        self.assertNotContains(resp, 'Also in:')
