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
from accounts.models import Reviewee, UserProfile
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle, ReviewerToken

from .admin_views import bulk_reviewees, plan_bulk_cycles


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

    def test_bulk_previous_source_copies_each_reviewees_latest_cycle(self):
        from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
        alice = RevieweeFactory(organization=self.org, email='alice@example.com')
        RevieweeFactory(organization=self.org, email='bob@example.com')  # no earlier cycle
        own = QuestionnaireFactory(organization=self.org)
        ReviewCycleFactory(reviewee=alice, questionnaire=self.questionnaire)  # older, ignored
        latest = ReviewCycleFactory(reviewee=alice, questionnaire=own, include_direct_report=False)
        ReviewerTokenFactory(cycle=latest, category='manager', reviewer_email='Boss@example.com')
        ReviewerTokenFactory(cycle=latest, category='peer', reviewer_email='pal@example.com')
        ReviewerTokenFactory(cycle=latest, category='peer')  # never assigned: not copied
        # The earlier self-assessment went to an address alice no longer has.
        ReviewerTokenFactory(cycle=latest, category='self', reviewer_email='old-alice@example.com')

        resp = self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'bulk_source': 'previous',  # no questionnaire: each cycle brings its own
        })
        self.assertEqual(resp.status_code, 302)

        new = ReviewCycle.objects.exclude(pk=latest.pk).filter(reviewee=alice).first()
        self.assertEqual(new.questionnaire, own)
        self.assertFalse(new.include_direct_report)
        emails = set(new.tokens.values_list('category', 'reviewer_email'))
        self.assertEqual(emails, {('manager', 'boss@example.com'), ('peer', 'pal@example.com'),
                                  ('self', 'alice@example.com')})
        self.assertFalse(ReviewCycle.objects.filter(reviewee__email='bob@example.com').exists())

    def test_bulk_preview_counts_the_cycles_and_creates_none(self):
        from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
        alice = RevieweeFactory(organization=self.org, email='alice@example.com')
        RevieweeFactory(organization=self.org, email='bob@example.com')
        previous = ReviewCycleFactory(reviewee=alice, questionnaire=self.questionnaire)
        ReviewerTokenFactory(cycle=previous, category='peer', reviewer_email='pal@example.com')
        people = Reviewee.objects.filter(organization=self.org, is_active=True).count()

        def preview(source):
            data = self.client.post(reverse('review_cycle_bulk_preview'), {'bulk_source': source}).json()
            return data['count'], data['skipped']

        self.assertEqual(preview('previous'), (1, people - 1))
        self.assertEqual(preview('empty'), (people, 0))
        self.assertEqual(preview('chart'), (0, people))  # nobody is in a unit
        self.assertEqual(ReviewCycle.objects.count(), 1)

    def test_bulk_run_for_selected_units_takes_only_their_managers_and_members(self):
        sam = RevieweeFactory(organization=self.org, email='sam@example.com')
        sue = RevieweeFactory(organization=self.org, email='sue@example.com')
        ed = RevieweeFactory(organization=self.org, email='ed@example.com')
        RevieweeFactory(organization=self.org, email='nounit@example.com')
        sales = OrgUnitFactory(organization=self.org, name='Sales')
        engineering = OrgUnitFactory(organization=self.org, name='Engineering')
        OrgUnitMembershipFactory(unit=sales, reviewee=sam, row=0, col=0)
        OrgUnitMembershipFactory(unit=sales, reviewee=sue, row=1, col=0)
        OrgUnitMembershipFactory(unit=engineering, reviewee=ed, row=1, col=0)
        form = {'creation_mode': 'bulk', 'bulk_source': 'empty', 'bulk_units': [str(sales.uuid)],
                'questionnaire': self.questionnaire.id}

        preview = self.client.post(reverse('review_cycle_bulk_preview'), form).json()
        self.assertEqual((preview['count'], preview['skipped']), (2, 0))

        self.client.post(reverse('review_cycle_create'), form)
        self.assertEqual(set(ReviewCycle.objects.values_list('reviewee__email', flat=True)),
                         {'sam@example.com', 'sue@example.com'})

    def test_bulk_run_refuses_a_unit_of_another_organization(self):
        # Dropping the unit instead would widen the run to everyone.
        RevieweeFactory(organization=self.org)
        foreign = OrgUnitFactory(organization=OrganizationFactory(), name='Elsewhere')
        form = {'creation_mode': 'bulk', 'bulk_source': 'empty', 'bulk_units': [str(foreign.uuid)],
                'questionnaire': self.questionnaire.id}

        for url in ('review_cycle_bulk_preview', 'review_cycle_create'):
            self.assertEqual(self.client.post(reverse(url), form).status_code, 404)
        self.assertFalse(ReviewCycle.objects.exists())

    def test_unplaced_reviewees_get_no_cycle_in_chart_mode(self):
        """
        A reviewee the chart gives no reviewers gets no cycle: a lone
        self-assessment is noise in the reports and costs a credit.
        """
        on_unit = RevieweeFactory(organization=self.org, name='OnUnit')
        loner = RevieweeFactory(organization=self.org, name='Loner')

        report = RevieweeFactory(organization=self.org, name='Report')

        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=on_unit, row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=report, row=1, col=0)

        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk',
            'bulk_source': 'chart',
            'questionnaire': str(self.questionnaire.id),
        })

        self.assertFalse(ReviewCycle.objects.filter(reviewee=loner).exists())
        self.assertTrue(ReviewCycle.objects.filter(reviewee=on_unit).exists())


class BulkLeavesOutDeactivatedPeopleTests(TestCase):
    """A deactivated person plays no part in a bulk run: no cycle, no invitation, not in the figures."""

    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory(username='bulk_admin')
        UserProfileFactory(user=self.admin, organization=self.org, can_create_cycles_for_others=True)
        _grant_manage(self.admin)
        self.questionnaire = QuestionnaireFactory(organization=self.org)
        # The manager left; the memberships stay in the chart.
        self.gone = RevieweeFactory(organization=self.org, email='gone@example.com', is_active=False)
        self.sam = RevieweeFactory(organization=self.org, name='Sam', email='sam@example.com')
        self.sue = RevieweeFactory(organization=self.org, name='Sue', email='sue@example.com')
        self.unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=self.unit, reviewee=self.gone, row=0, col=0)
        OrgUnitMembershipFactory(unit=self.unit, reviewee=self.sam, row=1, col=0)
        OrgUnitMembershipFactory(unit=self.unit, reviewee=self.sue, row=1, col=1)

    def test_a_deactivated_person_gets_no_cycle(self):
        self.assertNotIn(self.gone, bulk_reviewees(self.admin, self.org))
        self.assertEqual(set(bulk_reviewees(self.admin, self.org, [self.unit])), {self.sam, self.sue})

    def test_the_chart_invites_no_deactivated_person(self):
        # The only reviewer the chart gives this person is the manager who left.
        alone = RevieweeFactory(organization=self.org, email='alone@example.com')
        other = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=other, reviewee=self.gone, row=0, col=0)
        OrgUnitMembershipFactory(unit=other, reviewee=alone, row=1, col=0)

        planned, skipped = plan_bulk_cycles(
            bulk_reviewees(self.admin, self.org, [self.unit, other]), 'chart', self.questionnaire, {})

        self.assertEqual({reviewee: emails for reviewee, _q, _flags, emails in planned}, {
            self.sam: {'self': ['sam@example.com'], 'manager': [], 'peer': ['sue@example.com'], 'direct_report': []},
            self.sue: {'self': ['sue@example.com'], 'manager': [], 'peer': ['sam@example.com'], 'direct_report': []},
        })
        self.assertEqual(skipped, 1)

    def test_the_previous_cycle_invites_no_deactivated_person(self):
        from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
        previous = ReviewCycleFactory(reviewee=self.sam, questionnaire=self.questionnaire)
        ReviewerTokenFactory(cycle=previous, category='manager', reviewer_email='Gone@example.com')
        ReviewerTokenFactory(cycle=previous, category='peer', reviewer_email='external@elsewhere.example')
        # A deactivated person of another organization with that address: not ours to drop.
        RevieweeFactory(organization=OrganizationFactory(), email='external@elsewhere.example', is_active=False)
        # The only reviewer of Sue's previous cycle left.
        previous = ReviewCycleFactory(reviewee=self.sue, questionnaire=self.questionnaire)
        ReviewerTokenFactory(cycle=previous, category='manager', reviewer_email='gone@example.com')

        planned, skipped = plan_bulk_cycles(bulk_reviewees(self.admin, self.org, [self.unit]), 'previous', None, {})

        self.assertEqual({reviewee: emails for reviewee, _q, _flags, emails in planned}, {
            self.sam: {'self': ['sam@example.com'], 'manager': [], 'peer': ['external@elsewhere.example'],
                       'direct_report': []},
        })
        self.assertEqual(skipped, 1)


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
