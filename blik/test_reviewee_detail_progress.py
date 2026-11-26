from django.test import TestCase
from django.utils import timezone

from accounts.models import Reviewee
from blik.admin_views import cycle_progress
from core.models import Organization
from questionnaires.models import Questionnaire
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

        self.assertEqual([(row['category'], row['invited'], row['answered']) for row in rows],
                         [('self', 1, 1), ('peer', 3, 2), ('manager', 1, 1)])
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
