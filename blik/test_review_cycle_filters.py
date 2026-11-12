"""Review cycle list filters: stage, search and questionnaire narrow the
list; stage counts follow the other filters."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization
from questionnaires.models import Questionnaire
from reviews.models import ReviewCycle, ReviewerToken


class ReviewCycleFilterTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        org = Organization.objects.create(name='Acme', email='org@acme.example')
        admin = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=admin, organization=org)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        self.q1 = Questionnaire.objects.create(name='Engineering', organization=org)
        q2 = Questionnaire.objects.create(name='Manager', organization=org)

        def cycle(name, questionnaire, done, total, status='active'):
            reviewee = Reviewee.objects.create(
                organization=org, name=name, email=f'{name.lower()}@acme.example')
            c = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=questionnaire, status=status)
            for i in range(total):
                ReviewerToken.objects.create(
                    cycle=c, category='peer', completed_at=timezone.now() if i < done else None)
            return c

        self.waiting = cycle('Ann', self.q1, 0, 0)
        self.waiting_invited = cycle('Bob', q2, 0, 2)
        self.in_progress = cycle('Cas', self.q1, 1, 3)
        self.all_responded = cycle('Dee', q2, 2, 2)
        self.completed = cycle('Eve', self.q1, 1, 3, status='completed')

    def get(self, **params):
        return self.client.get(reverse('review_cycle_list'), params)

    def listed(self, response):
        return {c.pk for c in response.context['cycles']}

    def test_each_stage_lists_its_cycles(self):
        for stage, expected in [
            ('waiting', {self.waiting, self.waiting_invited}),
            ('in_progress', {self.in_progress}),
            ('all_responded', {self.all_responded}),
            ('completed', {self.completed}),
        ]:
            with self.subTest(stage=stage):
                self.assertEqual(self.listed(self.get(stage=stage)), {c.pk for c in expected})

    def test_stage_counts_cover_every_cycle_once(self):
        response = self.get()
        counts = {key: count for key, _label, count in response.context['stages']}
        self.assertEqual(counts, {'waiting': 2, 'in_progress': 1, 'all_responded': 1, 'completed': 1})
        self.assertEqual(response.context['total_count'], 5)

    def test_search_matches_name_or_email_and_narrows_counts(self):
        response = self.get(q='cas')
        self.assertEqual(self.listed(response), {self.in_progress.pk})
        self.assertEqual(self.listed(self.get(q='dee@acme')), {self.all_responded.pk})
        self.assertEqual(response.context['total_count'], 1)

    def test_questionnaire_filter_combines_with_stage(self):
        response = self.get(questionnaire=str(self.q1.uuid), stage='waiting')
        self.assertEqual(self.listed(response), {self.waiting.pk})

    def test_invalid_values_fall_back_to_unfiltered(self):
        response = self.get(questionnaire='not-a-uuid', stage='bogus', sort='bogus')
        self.assertEqual(len(self.listed(response)), 5)
        self.assertFalse(response.context['is_filtered'])

    def test_fewest_responses_sort(self):
        ordered = [c.pk for c in self.get(sort='fewest_responses').context['cycles']]
        self.assertEqual(set(ordered[:2]), {self.waiting.pk, self.waiting_invited.pk})
        self.assertEqual(ordered[-1], self.all_responded.pk)

    def test_cycles_of_deactivated_people_stay_listed_but_anonymized_ones_do_not(self):
        Reviewee.objects.filter(pk=self.completed.reviewee_id).update(is_active=False)
        Reviewee.objects.filter(pk=self.all_responded.reviewee_id).update(is_active=False, email='x@deleted.invalid')

        listed = self.listed(self.get())

        self.assertIn(self.completed.pk, listed)
        self.assertNotIn(self.all_responded.pk, listed)
