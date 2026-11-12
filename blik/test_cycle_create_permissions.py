"""Who may start a cycle for whom: only themselves, their direct reports too, or everyone."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_member, ensure_permission_groups
from core.models import Organization
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle

from .admin_views import creatable_reviewees


class CycleCreatePermissionTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')
        self.member = User.objects.create_user(username='m', email='member@acme.example', password='pw')
        UserProfile.objects.create(user=self.member, organization=self.org)
        assign_organization_member(self.member)
        self.own, _ = Reviewee.objects.get_or_create(
            organization=self.org, email='member@acme.example', defaults={'name': 'Member'})
        self.colleague = Reviewee.objects.create(organization=self.org, email='colleague@acme.example', name='Colleague')
        self.questionnaire = QuestionnaireFactory(organization=self.org)

    def test_member_may_only_create_for_themselves(self):
        self.assertEqual(list(creatable_reviewees(self.member, self.org)), [self.own])

    def with_permission_and_a_direct_report(self):
        """The member may create cycles for others and manages a unit with one member."""
        from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory
        self.member.profile.can_create_cycles_for_others = True
        self.member.profile.save()
        report = Reviewee.objects.create(organization=self.org, email='report@acme.example', name='Report')
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.own, row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=report, row=1, col=0)
        return report

    def test_member_with_permission_may_create_for_themselves_and_their_direct_reports(self):
        report = self.with_permission_and_a_direct_report()

        self.assertEqual(set(creatable_reviewees(self.member, self.org)), {self.own, report})

    def test_admin_with_permission_may_create_for_anyone(self):
        from accounts.permissions import assign_organization_admin
        self.member.profile.can_create_cycles_for_others = True
        self.member.profile.save()
        assign_organization_admin(self.member)
        admin = User.objects.get(pk=self.member.pk)  # without the cached permissions

        self.assertEqual(set(creatable_reviewees(admin, self.org)), {self.own, self.colleague})

    def test_bulk_of_a_manager_creates_for_the_own_team_only(self):
        report = self.with_permission_and_a_direct_report()
        self.client.force_login(self.member)

        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk', 'bulk_source': 'empty', 'questionnaire': self.questionnaire.id})

        self.assertEqual({c.reviewee for c in ReviewCycle.objects.all()}, {self.own, report})

    def test_a_manager_runs_the_cycles_of_their_direct_reports_and_no_others(self):
        from reviews.factories import ReviewCycleFactory
        report = self.with_permission_and_a_direct_report()
        self.client.force_login(self.member)

        def opens(reviewee):
            cycle = ReviewCycleFactory(reviewee=reviewee, questionnaire=self.questionnaire)
            return self.client.get(reverse('review_cycle_detail', args=[cycle.uuid])).status_code

        self.assertEqual((opens(report), opens(self.colleague)), (200, 404))

    def test_member_cannot_post_a_cycle_for_a_colleague(self):
        self.client.force_login(self.member)
        self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'single', 'questionnaire': self.questionnaire.id, 'reviewee': self.colleague.id})

        self.assertFalse(ReviewCycle.objects.filter(reviewee=self.colleague).exists())

    def test_member_cannot_post_bulk_cycles(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'bulk', 'questionnaire': self.questionnaire.id})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ReviewCycle.objects.exists())
