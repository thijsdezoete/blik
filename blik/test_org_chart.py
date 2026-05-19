"""
Tests for the org-chart backend (post-adaptive-slots refactor):

  - /dashboard/org-chart/ page
  - team create / rename / delete endpoints (no more shape config)
  - membership create / delete (role-based; server assigns row/col)
  - /dashboard/cycles/derive-reviewers/ endpoint
  - tree inference: a team whose manager is a member of another team nests
    under that parent's member slot
"""
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse


# Tests that render HTML pages touch {% static %} tags which, under the
# production ManifestStaticFilesStorage, demand a real collectstatic manifest.
# Swap in the plain filesystem backend for the duration of the test module
# so `{% static 'js/foo.js' %}` just returns '/static/js/foo.js'.
NON_HASHING_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

from accounts.factories import (
    RevieweeFactory,
    TeamFactory,
    TeamMembershipFactory,
    UserProfileFactory,
)
from accounts.models import Team, TeamMembership, UserProfile
from core.factories import OrganizationFactory, UserFactory


def _grant_manage(user):
    ct = ContentType.objects.get_for_model(UserProfile)
    perm, _ = Permission.objects.get_or_create(
        codename='can_manage_organization',
        content_type=ct,
        defaults={'name': 'Can manage organization settings'},
    )
    user.user_permissions.add(perm)


class OrgChartAdminSetup(TestCase):
    """Shared setup: an org, an admin user with manage perms, a second org."""

    def setUp(self):
        self.org = OrganizationFactory()
        self.other_org = OrganizationFactory()

        self.admin = UserFactory(username='oc_admin')
        UserProfileFactory(user=self.admin, organization=self.org,
                           can_create_cycles_for_others=True)
        _grant_manage(self.admin)
        self.client.force_login(self.admin)


@override_settings(STORAGES=NON_HASHING_STORAGES)
class PageRenderTests(OrgChartAdminSetup):
    def test_empty_state_when_no_teams(self):
        resp = self.client.get(reverse('org_chart'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No teams yet')

    def test_renders_team_cards(self):
        t = TeamFactory(organization=self.org, name='Leadership')
        alice = RevieweeFactory(organization=self.org, name='Alice Example')
        TeamMembershipFactory(team=t, reviewee=alice, row=0, col=0)

        resp = self.client.get(reverse('org_chart'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Leadership')
        self.assertContains(resp, 'Alice Example')

    def test_unplaced_pool_lists_untemped_reviewees(self):
        RevieweeFactory(organization=self.org, name='NotOnATeam')
        resp = self.client.get(reverse('org_chart'))
        self.assertContains(resp, 'NotOnATeam')

    def test_cross_org_teams_are_invisible(self):
        TeamFactory(organization=self.other_org, name='Foreign')
        resp = self.client.get(reverse('org_chart'))
        self.assertNotContains(resp, 'Foreign')


class TeamCreateTests(OrgChartAdminSetup):
    def test_creates_team_with_just_a_name(self):
        resp = self.client.post(reverse('org_chart_team_create'), {
            'name': 'Leadership',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('tree_html', data)
        self.assertIn('unplaced_html', data)
        self.assertTrue(Team.objects.filter(
            organization=self.org, name='Leadership').exists())

    def test_rejects_duplicate_name(self):
        TeamFactory(organization=self.org, name='Dup')
        resp = self.client.post(reverse('org_chart_team_create'), {
            'name': 'Dup',
        })
        self.assertEqual(resp.status_code, 400)

    def test_rejects_empty_name(self):
        resp = self.client.post(reverse('org_chart_team_create'), {
            'name': '   ',
        })
        self.assertEqual(resp.status_code, 400)

    def test_requires_permission(self):
        user = UserFactory(username='no_perm_oc')
        UserProfileFactory(user=user, organization=self.org)
        self.client.force_login(user)
        resp = self.client.post(reverse('org_chart_team_create'), {
            'name': 'X',
        })
        self.assertEqual(resp.status_code, 403)


class TeamUpdateDeleteTests(OrgChartAdminSetup):
    def setUp(self):
        super().setUp()
        self.team = TeamFactory(organization=self.org, name='Engineering')

    def test_rename(self):
        url = reverse('org_chart_team_update', args=[self.team.uuid])
        resp = self.client.post(url, {'name': 'Eng'})
        self.assertEqual(resp.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, 'Eng')

    def test_rename_rejects_collision(self):
        TeamFactory(organization=self.org, name='Taken')
        url = reverse('org_chart_team_update', args=[self.team.uuid])
        resp = self.client.post(url, {'name': 'Taken'})
        self.assertEqual(resp.status_code, 400)

    def test_cross_org_team_returns_404(self):
        foreign = TeamFactory(organization=self.other_org, name='Foreign')
        url = reverse('org_chart_team_update', args=[foreign.uuid])
        resp = self.client.post(url, {'name': 'hacked'})
        self.assertEqual(resp.status_code, 404)

    def test_delete_team(self):
        url = reverse('org_chart_team_delete', args=[self.team.uuid])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())


class MembershipCreateTests(OrgChartAdminSetup):
    def setUp(self):
        super().setUp()
        self.team = TeamFactory(organization=self.org, name='T')
        self.alice = RevieweeFactory(organization=self.org, name='Alice')
        self.bob = RevieweeFactory(organization=self.org, name='Bob')

    def _create(self, **params):
        defaults = {
            'team_uuid': str(self.team.uuid),
            'reviewee_uuid': str(self.alice.uuid),
            'role': 'manager',
        }
        defaults.update(params)
        return self.client.post(reverse('org_chart_membership_create'), defaults)

    def test_adds_a_manager(self):
        resp = self._create(role='manager')
        self.assertEqual(resp.status_code, 200)
        m = TeamMembership.objects.get(team=self.team, reviewee=self.alice)
        self.assertEqual(m.role, TeamMembership.MANAGER)
        self.assertEqual((m.row, m.col), (0, 0))

    def test_adds_a_member(self):
        resp = self._create(role='member')
        self.assertEqual(resp.status_code, 200)
        m = TeamMembership.objects.get(team=self.team, reviewee=self.alice)
        self.assertEqual(m.role, TeamMembership.MEMBER)
        self.assertEqual((m.row, m.col), (1, 0))

    def test_appends_at_next_col(self):
        """Server assigns col sequentially — no slot coordinates from client."""
        self._create(role='manager')
        self._create(role='manager', reviewee_uuid=str(self.bob.uuid))
        cols = sorted(TeamMembership.objects.filter(
            team=self.team, role=TeamMembership.MANAGER,
        ).values_list('col', flat=True))
        self.assertEqual(cols, [0, 1])

    def test_rejects_unknown_role(self):
        resp = self._create(role='boss')
        self.assertEqual(resp.status_code, 400)

    def test_rejects_duplicate_person_on_same_team(self):
        self._create(role='manager')
        resp = self._create(role='member')  # same reviewee, different role
        self.assertEqual(resp.status_code, 400)

    def test_cross_org_reviewee_returns_404(self):
        foreigner = RevieweeFactory(organization=self.other_org)
        resp = self._create(reviewee_uuid=str(foreigner.uuid))
        self.assertEqual(resp.status_code, 404)

    def test_move_mode_removes_from_source_team(self):
        team_b = TeamFactory(organization=self.org, name='B')
        TeamMembershipFactory(team=self.team, reviewee=self.alice, row=1, col=0)

        resp = self.client.post(reverse('org_chart_membership_create'), {
            'team_uuid': str(team_b.uuid),
            'reviewee_uuid': str(self.alice.uuid),
            'role': 'member',
            'mode': 'move',
            'source_team_uuid': str(self.team.uuid),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TeamMembership.objects.filter(
            team=self.team, reviewee=self.alice).exists())
        self.assertTrue(TeamMembership.objects.filter(
            team=team_b, reviewee=self.alice).exists())


class MembershipDeleteTests(OrgChartAdminSetup):
    def test_deletes_membership(self):
        team = TeamFactory(organization=self.org, name='T')
        alice = RevieweeFactory(organization=self.org)
        m = TeamMembershipFactory(team=team, reviewee=alice, row=0, col=0)

        url = reverse('org_chart_membership_delete', args=[m.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TeamMembership.objects.filter(pk=m.pk).exists())

    def test_cannot_delete_membership_from_other_org(self):
        foreign_team = TeamFactory(organization=self.other_org)
        foreign_person = RevieweeFactory(organization=self.other_org)
        m = TeamMembershipFactory(
            team=foreign_team, reviewee=foreign_person, row=0, col=0)

        url = reverse('org_chart_membership_delete', args=[m.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)


@override_settings(STORAGES=NON_HASHING_STORAGES)
class TreeInferenceTests(OrgChartAdminSetup):
    """
    A team whose manager is a member of another team should nest under that
    parent in the rendered chart.
    """

    def test_child_team_nests_under_parent(self):
        # Leadership: CEO (mgr), VP (member)
        # Engineering: VP (mgr), Alice (member)
        # → Engineering should visually sit inside Leadership's VP slot
        ceo = RevieweeFactory(organization=self.org, name='CEO')
        vp = RevieweeFactory(organization=self.org, name='VP Eng')
        alice = RevieweeFactory(organization=self.org, name='Alice')

        leadership = TeamFactory(organization=self.org, name='Leadership')
        TeamMembershipFactory(team=leadership, reviewee=ceo, row=0, col=0)
        TeamMembershipFactory(team=leadership, reviewee=vp, row=1, col=0)

        engineering = TeamFactory(organization=self.org, name='Engineering')
        TeamMembershipFactory(team=engineering, reviewee=vp, row=0, col=0)
        TeamMembershipFactory(team=engineering, reviewee=alice, row=1, col=0)

        resp = self.client.get(reverse('org_chart'))
        html = resp.content.decode()

        # Engineering's card must live inside the `.oc-children` wrapper that
        # hangs off Leadership's tree-node. We check: Leadership's card appears
        # first, then an `.oc-children` opener, then Engineering's card.
        leadership_marker = f'data-team-uuid="{leadership.uuid}"'
        engineering_marker = f'data-team-uuid="{engineering.uuid}"'

        leadership_idx = html.find(leadership_marker)
        engineering_idx = html.find(engineering_marker)
        self.assertNotEqual(leadership_idx, -1)
        self.assertNotEqual(engineering_idx, -1)

        children_idx = html.find('class="oc-children"', leadership_idx)
        self.assertNotEqual(children_idx, -1,
                            "Expected Leadership to have an oc-children block")
        self.assertLess(leadership_idx, children_idx)
        self.assertLess(children_idx, engineering_idx,
                        "Engineering card should be rendered inside the "
                        "oc-children block that hangs off Leadership")

    def test_breaks_cycle_without_infinite_recursion(self):
        """
        Pathological cycle (A's mgr is member of B, B's mgr is member of A).
        Both teams should still render — neither can be the child of the
        other. The view should not recurse forever.
        """
        a_person = RevieweeFactory(organization=self.org, name='A-person')
        b_person = RevieweeFactory(organization=self.org, name='B-person')

        team_a = TeamFactory(organization=self.org, name='TeamA')
        team_b = TeamFactory(organization=self.org, name='TeamB')
        # A's manager = a_person; a_person is a member of B
        TeamMembershipFactory(team=team_a, reviewee=a_person, row=0, col=0)
        TeamMembershipFactory(team=team_b, reviewee=a_person, row=1, col=0)
        # B's manager = b_person; b_person is a member of A
        TeamMembershipFactory(team=team_b, reviewee=b_person, row=0, col=0)
        TeamMembershipFactory(team=team_a, reviewee=b_person, row=1, col=0)

        resp = self.client.get(reverse('org_chart'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('TeamA', html)
        self.assertIn('TeamB', html)


class TeamSetParentTests(OrgChartAdminSetup):
    """
    `org_chart_team_set_parent` is the explicit 'make team X report to
    team Y' action. Mechanically it adds X's first manager as a member
    of Y; the tree then renders X nested under Y.
    """

    def setUp(self):
        super().setUp()
        self.vp = RevieweeFactory(organization=self.org, name='VP Eng')
        self.ceo = RevieweeFactory(organization=self.org, name='CEO')

        self.leadership = TeamFactory(organization=self.org, name='Leadership')
        TeamMembershipFactory(team=self.leadership, reviewee=self.ceo, row=0, col=0)

        # Engineering has a manager but no parent yet — the "root" case
        # the new action was designed to fix.
        self.engineering = TeamFactory(organization=self.org, name='Engineering')
        TeamMembershipFactory(team=self.engineering, reviewee=self.vp, row=0, col=0)

    def _post(self, child, parent_uuid):
        url = reverse('org_chart_team_set_parent', args=[child.uuid])
        return self.client.post(url, {'parent_team_uuid': parent_uuid})

    def test_adds_first_manager_to_parent(self):
        resp = self._post(self.engineering, str(self.leadership.uuid))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(TeamMembership.objects.filter(
            team=self.leadership, reviewee=self.vp,
            role=TeamMembership.MEMBER,
        ).exists())

    def test_refuses_self(self):
        resp = self._post(self.engineering, str(self.engineering.uuid))
        self.assertEqual(resp.status_code, 400)

    def test_refuses_when_child_has_no_manager(self):
        bare = TeamFactory(organization=self.org, name='Bare')
        resp = self._post(bare, str(self.leadership.uuid))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Add a manager', resp.json()['error'])

    def test_refuses_cycle(self):
        # Engineering currently reports to Leadership (via VP as member).
        self._post(self.engineering, str(self.leadership.uuid))

        # Attempting to make Leadership report to Engineering would close
        # the loop — refuse.
        resp = self._post(self.leadership, str(self.engineering.uuid))
        self.assertEqual(resp.status_code, 400)

    def test_refuses_when_manager_is_manager_of_target(self):
        """
        If VP is already a MANAGER of Leadership, making Engineering report
        to Leadership would require VP to also be a member — disallowed.
        """
        # Remove CEO's manager chip and put VP there instead.
        self.leadership.memberships.all().delete()
        TeamMembershipFactory(
            team=self.leadership, reviewee=self.vp, row=0, col=0)

        resp = self._post(self.engineering, str(self.leadership.uuid))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('manages', resp.json()['error'])

    def test_cross_org_target_returns_404(self):
        foreign = TeamFactory(organization=self.other_org, name='Foreign')
        resp = self._post(self.engineering, str(foreign.uuid))
        self.assertEqual(resp.status_code, 404)


class DeriveReviewersEndpointTests(OrgChartAdminSetup):
    def test_returns_buckets_as_json(self):
        alice = RevieweeFactory(organization=self.org, name='Alice')
        ceo = RevieweeFactory(organization=self.org, name='CEO')
        team = TeamFactory(organization=self.org, name='Team')
        TeamMembershipFactory(team=team, reviewee=ceo, row=0, col=0)
        TeamMembershipFactory(team=team, reviewee=alice, row=1, col=0)

        resp = self.client.get(
            reverse('derive_reviewers_for_cycle'),
            {'reviewee': str(alice.uuid)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual([r['uuid'] for r in data['self']], [str(alice.uuid)])
        self.assertEqual([r['uuid'] for r in data['manager']], [str(ceo.uuid)])
        self.assertEqual(data['peer'], [])
        self.assertEqual(data['direct_report'], [])

    def test_missing_reviewee_param_returns_400(self):
        resp = self.client.get(reverse('derive_reviewers_for_cycle'))
        self.assertEqual(resp.status_code, 400)

    def test_cross_org_uuid_returns_404(self):
        foreigner = RevieweeFactory(organization=self.other_org)
        resp = self.client.get(
            reverse('derive_reviewers_for_cycle'),
            {'reviewee': str(foreigner.uuid)},
        )
        self.assertEqual(resp.status_code, 404)

    def test_empty_chart_returns_only_self(self):
        lonely = RevieweeFactory(organization=self.org, name='Lonely')
        resp = self.client.get(
            reverse('derive_reviewers_for_cycle'),
            {'reviewee': str(lonely.uuid)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['self']), 1)
        self.assertEqual(data['manager'], [])
        self.assertEqual(data['peer'], [])
        self.assertEqual(data['direct_report'], [])
