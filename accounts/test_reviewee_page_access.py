"""Who may open the page of one reviewee, and what the page lets them do."""
from django.contrib.auth.models import User
from django.test import TestCase

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory
from accounts.models import Reviewee, UserProfile
from accounts.permissions import (
    assign_organization_admin,
    assign_organization_member,
    ensure_permission_groups,
    reviewee_page_access,
    set_user_permission,
)
from core.models import Organization


class RevieweePageAccessTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')
        self.reviewee = Reviewee.objects.create(
            organization=self.org, name='Dana Doe', email='dana@acme.example')

    def make_user(self, name, email=None):
        user = User.objects.create_user(
            username=name, email=email or f'{name}@acme.example', password='pw')
        UserProfile.objects.create(user=user, organization=self.org)
        assign_organization_member(user)
        return user

    def fresh(self, user):
        """The user without cached permissions."""
        return User.objects.get(pk=user.pk)

    def make_manager_of(self, user, reviewee):
        own, _ = Reviewee.objects.get_or_create(
            organization=self.org, email=user.email, defaults={'name': user.username})
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=own, row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=reviewee, row=1, col=0)

    def test_admin_can_do_everything(self):
        admin = self.make_user('admin')
        assign_organization_admin(admin)

        self.assertEqual(
            reviewee_page_access(self.fresh(admin),self.org, self.reviewee),
            {'manage': True, 'setup': True, 'chart': True, 'reader': 'all'})

    def test_report_reader_sees_all_and_sets_nothing(self):
        reader = self.make_user('reader')
        set_user_permission(reader, 'can_view_all_reports', True)

        self.assertEqual(
            reviewee_page_access(self.fresh(reader), self.org, self.reviewee),
            {'manage': False, 'setup': False, 'chart': False, 'reader': 'all'})

    def test_manager_reads_a_direct_report(self):
        manager = self.make_user('manager')
        self.make_manager_of(manager, self.reviewee)

        self.assertEqual(
            reviewee_page_access(manager, self.org, self.reviewee),
            {'manage': False, 'setup': False, 'chart': False, 'reader': 'manager'})

    def test_manager_who_creates_for_others_can_set_up_a_direct_report(self):
        manager = self.make_user('manager')
        self.make_manager_of(manager, self.reviewee)
        manager.profile.can_create_cycles_for_others = True
        manager.profile.save()

        self.assertEqual(
            reviewee_page_access(self.fresh(manager), self.org, self.reviewee),
            {'manage': False, 'setup': True, 'chart': False, 'reader': 'manager'})

    def test_reviewee_can_set_up_their_own_review(self):
        own = self.make_user('dana', email='Dana@Acme.example')

        self.assertEqual(
            reviewee_page_access(own, self.org, self.reviewee),
            {'manage': False, 'setup': True, 'chart': False, 'reader': 'own'})

    def test_colleague_gets_nothing(self):
        colleague = self.make_user('colleague')

        self.assertIsNone(reviewee_page_access(colleague, self.org, self.reviewee))

    def test_person_of_another_organization_gets_nothing(self):
        other_org = Organization.objects.create(name='Other', email='org@other.example')
        outsider = Reviewee.objects.create(
            organization=other_org, name='Dana Doe', email='dana@acme.example')
        admin = self.make_user('admin')
        assign_organization_admin(admin)

        self.assertIsNone(reviewee_page_access(self.fresh(admin), self.org, outsider))
