from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory, UserProfileFactory
from accounts.models import Reviewee
from accounts.permissions import assign_organization_admin, assign_organization_member
from blik.admin_views import cycle_progress
from core.models import Organization
from questionnaires.factories import QuestionnaireFactory
from questionnaires.models import Questionnaire
from reviews.factories import ReviewCycleFactory
from reviews.models import ReviewCycle, ReviewerToken


class CycleProgressTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='Acme', email='org@acme.example', min_responses_for_anonymity=3,
        )
        questionnaire = Questionnaire.objects.create(name='Skills', organization=self.organization)
        reviewee = Reviewee.objects.create(
            name='Maya Jansen', email='maya@acme.example', department='Product Engineering',
            organization=self.organization,
        )
        self.cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=questionnaire)

    def invite(self, category, invited, answered):
        for n in range(invited):
            ReviewerToken.objects.create(
                cycle=self.cycle, category=category, reviewer_email=f'{category}{n}@acme.example',
                completed_at=timezone.now() if n < answered else None,
            )

    def row(self, category):
        return next(row for row in cycle_progress(self.cycle) if row['category'] == category)

    def test_counts_per_category(self):
        self.invite('self', 1, 1)
        self.invite('manager', 1, 1)
        self.invite('peer', 3, 2)
        self.invite('direct_report', 2, 0)
        self.cycle.include_direct_report = False
        self.cycle.save()

        rows = cycle_progress(self.cycle)

        # In the order of the reviewers card
        self.assertEqual([(row['category'], row['invited'], row['answered']) for row in rows],
                         [('self', 1, 1), ('manager', 1, 1), ('peer', 3, 2)])
        self.assertEqual(set(rows[0]), {'category', 'invited', 'answered', 'shows', 'needed'})

    def test_group_under_the_threshold_does_not_show(self):
        self.invite('self', 1, 0)
        self.invite('manager', 1, 0)
        self.invite('direct_report', 2, 2)

        self.assertEqual(self.row('direct_report')['shows'], 'no')
        self.assertEqual(self.row('peer')['shows'], 'no')
        # The self-assessment and the manager show at any count
        self.assertEqual(self.row('self')['shows'], 'yes')
        self.assertEqual(self.row('manager')['shows'], 'yes')

    def test_one_more_answer_needed(self):
        self.invite('peer', 3, 2)
        self.assertEqual((self.row('peer')['shows'], self.row('peer')['needed']), ('not_yet', 1))

        ReviewerToken.objects.filter(cycle=self.cycle, completed_at__isnull=True).update(completed_at=timezone.now())
        self.assertEqual((self.row('peer')['shows'], self.row('peer')['needed']), ('yes', 0))


class RevieweeDetailCurrentReviewTests(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.org = self.profile.organization
        assign_organization_admin(self.profile.user)
        self.alex = RevieweeFactory(organization=self.org, name='Alex Morgan', email='alex@acme.example',
                                    department='Product Engineering')
        self.older = ReviewCycleFactory(reviewee=self.alex, questionnaire=QuestionnaireFactory(organization=self.org))
        self.newer = ReviewCycleFactory(reviewee=self.alex, questionnaire=QuestionnaireFactory(organization=self.org))
        ReviewCycle.objects.filter(pk=self.older.pk).update(created_at=timezone.now() - timedelta(days=30))
        self.url = reverse('reviewee_detail', args=[self.alex.uuid])

    def page(self, user):
        self.client.force_login(user)
        return self.client.get(self.url).context

    def test_two_active_cycles_give_two_blocks(self):
        ReviewerToken.objects.create(cycle=self.newer, category='peer', reviewer_email='dana@acme.example',
                                     completed_at=timezone.now())
        ReviewCycleFactory(reviewee=self.alex, questionnaire=self.newer.questionnaire, status='completed')

        reviews = self.page(self.profile.user)['current_reviews']

        self.assertEqual([review['cycle'] for review in reviews], [self.newer, self.older])
        # Each row of cycle_progress, with the label of its category for the table
        self.assertEqual([[{key: value for key, value in row.items() if key != 'label'} for row in review['progress']]
                          for review in reviews],
                         [cycle_progress(self.newer), cycle_progress(self.older)])
        self.assertEqual(
            [(review['answered'], review['invited']) for review in reviews],
            [(self.newer.tokens.filter(completed_at__isnull=False).count(), self.newer.tokens.count()),
             (0, self.older.tokens.count())])

    def test_cycle_links_for_a_user_who_may_run_the_cycle(self):
        context = self.page(self.profile.user)

        self.assertEqual([review['runs'] for review in context['current_reviews']], [True, True])
        self.assertEqual(context['reminder_cycle'], self.newer)

    def manager_of_alex(self, may_create_for_others=False):
        manager = UserProfileFactory(organization=self.org, user__email='hank@acme.example').user
        assign_organization_member(manager, can_create_cycles_for_others=may_create_for_others)
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=Reviewee.objects.get(email='hank@acme.example'), row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.alex, row=1, col=0)
        return manager

    def test_manager_who_only_reads_gets_no_cycle_links(self):
        context = self.page(self.manager_of_alex())

        self.assertEqual(context['access']['reader'], 'manager')
        self.assertEqual([review['runs'] for review in context['current_reviews']], [False, False])
        self.assertIsNone(context['reminder_cycle'])

    def test_manager_with_the_create_right_gets_the_cycle_links(self):
        context = self.page(self.manager_of_alex(may_create_for_others=True))

        self.assertEqual(context['access']['reader'], 'manager')
        self.assertEqual([review['runs'] for review in context['current_reviews']], [True, True])
        self.assertEqual(context['reminder_cycle'], self.newer)

    def test_reviewee_gets_the_links_of_their_own_cycle(self):
        # The app lets a reviewee open their own cycle today; a change of that rule shows here
        reviewee = UserProfileFactory(organization=self.org, user__email='alex@acme.example').user
        assign_organization_member(reviewee)

        context = self.page(reviewee)

        self.assertEqual(context['access']['reader'], 'own')
        self.assertEqual([review['runs'] for review in context['current_reviews']], [True, True])
        self.assertEqual(context['reminder_cycle'], self.newer)
