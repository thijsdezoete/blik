"""Granting can_view_all_reports to a single member from the team UI.

The permission existed but was only ever handed out in a bundle, through the
Organization Admin group. These tests cover the per-user grant: the team view
writes it, and reports/views.py honours it.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Reviewee, UserProfile
from accounts.permissions import (
    assign_organization_admin,
    assign_organization_member,
    ensure_permission_groups,
)
from core.models import Organization
from questionnaires.models import Questionnaire
from reviews.models import ReviewCycle


class TeamPermissionTestCase(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')

        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

        # A second admin, so demoting the first is not blocked as "last admin".
        self.other_admin = User.objects.create_user(
            username='admin2', email='admin2@acme.example', password='pw')
        UserProfile.objects.create(user=self.other_admin, organization=self.org)
        assign_organization_admin(self.other_admin)

        self.member = User.objects.create_user(
            username='member', email='member@acme.example', password='pw')
        self.member_profile = UserProfile.objects.create(
            user=self.member, organization=self.org)
        assign_organization_member(self.member)

    def _reload(self, user):
        """Re-fetch so has_perm() does not answer from its cache."""
        return User.objects.get(pk=user.pk)

    def _post(self, profile, **fields):
        data = {'user_profile_id': profile.id, 'role': 'member'}
        data.update(fields)
        return self.client.post(reverse('update_user_permissions'), data)


class ReportAccessGrantTests(TeamPermissionTestCase):
    def test_member_has_no_report_access_by_default(self):
        self.assertFalse(
            self._reload(self.member).has_perm('accounts.can_view_all_reports'))

    def test_admin_grants_report_access_to_a_member(self):
        self.client.force_login(self.admin)
        self._post(self.member_profile, can_view_all_reports='on')

        self.assertTrue(
            self._reload(self.member).has_perm('accounts.can_view_all_reports'))

    def test_admin_revokes_report_access_again(self):
        self.client.force_login(self.admin)
        self._post(self.member_profile, can_view_all_reports='on')
        self._post(self.member_profile)

        self.assertFalse(
            self._reload(self.member).has_perm('accounts.can_view_all_reports'))

    def test_grant_leaves_the_member_a_member(self):
        """The point of the permission: report access without being an admin."""
        self.client.force_login(self.admin)
        self._post(self.member_profile, can_view_all_reports='on')

        member = self._reload(self.member)
        self.assertTrue(member.has_perm('accounts.can_view_all_reports'))
        self.assertFalse(member.has_perm('accounts.can_manage_organization'))
        self.assertFalse(member.is_staff)

    def test_promotion_does_not_leave_a_direct_grant_behind(self):
        """Admins hold it through their group; a direct grant would outlive the role."""
        self.client.force_login(self.admin)
        self.client.post(reverse('update_user_permissions'), {
            'user_profile_id': self.member_profile.id,
            'role': 'admin',
            'can_view_all_reports': 'on',
        })

        promoted = self._reload(self.member)
        self.assertTrue(promoted.has_perm('accounts.can_view_all_reports'))
        self.assertFalse(
            promoted.user_permissions.filter(codename='can_view_all_reports').exists())

    def test_demotion_without_the_box_takes_report_access_away(self):
        self.client.force_login(self.admin)
        profile = UserProfile.objects.get(user=self.other_admin)

        self._post(profile)

        self.assertFalse(
            self._reload(self.other_admin).has_perm('accounts.can_view_all_reports'))

    def test_demotion_with_the_box_keeps_report_access(self):
        self.client.force_login(self.admin)
        profile = UserProfile.objects.get(user=self.other_admin)

        self._post(profile, can_view_all_reports='on')

        demoted = self._reload(self.other_admin)
        self.assertTrue(demoted.has_perm('accounts.can_view_all_reports'))
        self.assertFalse(demoted.has_perm('accounts.can_manage_organization'))

    def test_a_member_cannot_grant_it_to_themselves(self):
        self.client.force_login(self.member)
        self._post(self.member_profile, can_view_all_reports='on')

        self.assertFalse(
            self._reload(self.member).has_perm('accounts.can_view_all_reports'))


class ApiAccessGrantTests(TeamPermissionTestCase):
    """API access is in no group: an admin sets it per user, for members,
    for other admins and for their own account."""

    def _has_api_access(self, user):
        return self._reload(user).has_perm('accounts.can_use_api')

    def test_nobody_has_api_access_by_default(self):
        self.assertFalse(self._has_api_access(self.admin))
        self.assertFalse(self._has_api_access(self.member))

    def test_admin_grants_api_access_to_a_member(self):
        self.client.force_login(self.admin)
        self._post(self.member_profile, can_use_api='on')

        self.assertTrue(self._has_api_access(self.member))
        self.assertFalse(
            self._reload(self.member).has_perm('accounts.can_manage_organization'))

    def test_admin_grants_api_access_to_another_admin(self):
        self.client.force_login(self.admin)
        profile = UserProfile.objects.get(user=self.other_admin)

        self._post(profile, role='admin', can_use_api='on')

        self.assertTrue(self._has_api_access(self.other_admin))
        self.assertTrue(
            self._reload(self.other_admin).has_perm('accounts.can_manage_organization'))

    def test_admin_withdraws_api_access_again(self):
        self.client.force_login(self.admin)
        self._post(self.member_profile, can_use_api='on')
        self._post(self.member_profile)

        self.assertFalse(self._has_api_access(self.member))

    def test_admin_grants_api_access_to_themselves(self):
        self.client.force_login(self.admin)
        self._post(UserProfile.objects.get(user=self.admin), role='admin', can_use_api='on')

        self.assertTrue(self._has_api_access(self.admin))

    def test_admin_changes_nothing_else_on_their_own_account(self):
        """No self-demotion: only API access is read from the form."""
        self.client.force_login(self.admin)
        self._post(UserProfile.objects.get(user=self.admin), can_use_api='on')

        self.assertTrue(
            self._reload(self.admin).has_perm('accounts.can_manage_organization'))

    def test_a_member_cannot_grant_it_to_themselves(self):
        self.client.force_login(self.member)
        self._post(self.member_profile, can_use_api='on')

        self.assertFalse(self._has_api_access(self.member))


class ReportAccessEffectTests(TeamPermissionTestCase):
    """What the permission is for: reading a report that is not your own."""

    def setUp(self):
        super().setUp()
        reviewee = Reviewee.objects.create(
            organization=self.org, name='Dana Doe', email='dana@acme.example')
        questionnaire = Questionnaire.objects.create(
            name='Professional Skills', organization=self.org)
        self.cycle = ReviewCycle.objects.create(
            reviewee=reviewee, questionnaire=questionnaire, status='active')

    def _report_url(self):
        return reverse('reports:view_report', args=[self.cycle.uuid])

    def test_member_without_the_permission_cannot_open_a_foreign_report(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self._report_url()).status_code, 404)

    def test_member_with_the_permission_can_open_it(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('update_user_permissions'), {
            'user_profile_id': self.member_profile.id,
            'role': 'member',
            'can_view_all_reports': 'on',
        })

        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self._report_url()).status_code, 200)


class CycleVisibilityTests(TeamPermissionTestCase):
    """can_view_all_reports also widens visible_cycles(), so the grant covers
    every cycle in the organization — a report is only reachable through its
    cycle. The team UI says so."""

    def setUp(self):
        super().setUp()
        reviewee = Reviewee.objects.create(
            organization=self.org, name='Dana Doe', email='dana@acme.example')
        questionnaire = Questionnaire.objects.create(
            name='Professional Skills', organization=self.org)
        ReviewCycle.objects.create(
            reviewee=reviewee, questionnaire=questionnaire, status='active')

    def test_member_sees_no_foreign_cycle_by_default(self):
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(reverse('review_cycle_list')), 'Dana Doe')

    def test_grant_also_reveals_foreign_cycles(self):
        self.client.force_login(self.admin)
        self._post(self.member_profile, can_view_all_reports='on')

        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse('review_cycle_list')), 'Dana Doe')


class TeamListDisplayTests(TeamPermissionTestCase):
    """Admins already carry the badge through their group, so assert on the
    member's own row: the modal call that opens it states the member's state."""

    def _member_modal_call(self, grants_reports):
        return "'member', false, false, {}".format(
            'true' if grants_reports else 'false')

    def test_member_row_starts_without_report_access(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('team_list'))

        self.assertContains(response, self._member_modal_call(False))

    def test_member_row_reflects_the_grant(self):
        self.client.force_login(self.admin)
        self._post(self.member_profile, can_view_all_reports='on')

        response = self.client.get(reverse('team_list'))
        self.assertContains(response, self._member_modal_call(True))

    def test_grant_adds_one_badge_per_rendered_row(self):
        """Each user is rendered twice — desktop table and mobile card."""
        self.client.force_login(self.admin)
        before = self.client.get(reverse('team_list')).content.count(b'All reports')

        self._post(self.member_profile, can_view_all_reports='on')
        after = self.client.get(reverse('team_list')).content.count(b'All reports')

        self.assertEqual(after, before + 2)
