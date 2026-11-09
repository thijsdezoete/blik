"""Members without can_create_cycles_for_others start cycles only for themselves."""
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

    def test_member_with_permission_may_create_for_anyone(self):
        self.member.profile.can_create_cycles_for_others = True
        self.member.profile.save()

        self.assertEqual(set(creatable_reviewees(self.member, self.org)), {self.own, self.colleague})

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
