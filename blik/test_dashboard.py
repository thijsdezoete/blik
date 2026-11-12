"""The state the dashboard shows: what Blik knows about running cycles, and what it does not."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory
from blik import dashboard
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.models import ReviewCycle


class DashboardStateTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory(min_responses_for_anonymity=3)
        self.questionnaire = QuestionnaireFactory(organization=self.org)
        self.now = timezone.now()

    def cycle(self, name='Ann', **tokens):
        """A cycle with tokens per group as (answered, total); `email=True` invites them by email."""
        by_email = tokens.pop('email', False)
        reviewee = RevieweeFactory(organization=self.org, name=name, email=f'{name.lower()}@acme.example')
        cycle = ReviewCycleFactory(reviewee=reviewee, questionnaire=self.questionnaire)
        for group, (answered, total) in tokens.items():
            for i in range(total):
                ReviewerTokenFactory(
                    cycle=cycle, category=group,
                    reviewer_email=f'{group}{i}@acme.example' if by_email else None,
                    completed_at=self.now if i < answered else None)
        return cycle

    def stage_of(self, cycle):
        cycles = dashboard.with_progress(ReviewCycle.objects.filter(pk=cycle.pk))
        return [key for key, (_label, condition) in dashboard.cycle_stages(3).items()
                if cycles.filter(condition).exists()]

    def test_enough_needs_every_group_with_reviewers_at_the_threshold(self):
        self.assertEqual(self.stage_of(self.cycle('A', peer=(3, 5))), ['enough'])
        # The manager group has a reviewer but is below the threshold.
        self.assertEqual(self.stage_of(self.cycle('B', peer=(3, 5), manager=(0, 1))), ['collecting'])
        # All who are there answered, but two answers are not enough for a report.
        self.assertEqual(self.stage_of(self.cycle('C', peer=(2, 2))), ['collecting'])
        self.assertEqual(self.stage_of(self.cycle('D', peer=(0, 2))), ['waiting'])

    def test_a_group_the_cycle_does_not_collect_is_not_counted(self):
        cycle = self.cycle('A', peer=(3, 3), manager=(0, 1))
        ReviewCycle.objects.filter(pk=cycle.pk).update(include_manager=False)

        self.assertEqual(self.stage_of(cycle), ['enough'])

    def test_running_state_separates_invited_reviewers_from_shared_links(self):
        self.cycle('A', peer=(1, 4), email=True)
        self.cycle('B', peer=(2, 2))

        state = dashboard.running_state(ReviewCycle.objects.all(), 3, self.now)

        self.assertEqual((state['cycles'], state['answers']), (2, 3))
        self.assertEqual((state['invited_answered'], state['invited']), (1, 4))
        self.assertEqual(state['link_answers'], 2)
        self.assertEqual({s['key']: s['count'] for s in state['stages']},
                         {'waiting': 0, 'collecting': 2, 'enough': 0})

    def test_running_state_is_empty_without_an_active_cycle(self):
        self.assertIsNone(dashboard.running_state(ReviewCycle.objects.all(), 3, self.now))

    def test_needs_names_stale_cycles_and_cycles_without_reviewers(self):
        stale = self.cycle('A', peer=(0, 2))
        fresh = self.cycle('B', peer=(0, 2))
        empty = self.cycle('C')
        old = self.now - timedelta(days=8)
        ReviewCycle.objects.filter(pk__in=[stale.pk, empty.pk]).update(created_at=old)

        state = dashboard.running_state(ReviewCycle.objects.all(), 3, self.now)

        self.assertEqual({key: need['count'] for key, need in state['needs'].items()},
                         {'failed_emails': 0, 'stale': 1, 'no_reviewers': 1})
        self.assertTrue(fresh.pk)  # the fresh cycle is in neither

    def test_getting_started_follows_what_the_organization_did(self):
        started = dashboard.getting_started(self.org)
        self.assertEqual((started['done'], started['complete']), (0, False))

        self.cycle('A', peer=(1, 2))
        started = dashboard.getting_started(self.org)

        self.assertEqual([step['done'] for step in started['steps']], [True, True, True, False])
        self.assertEqual([step['key'] for step in started['steps'] if step['next']], ['report'])

    def test_a_person_sees_the_feedback_colleagues_wait_for_and_their_team(self):
        manager = RevieweeFactory(organization=self.org, name='Mia', email='mia@acme.example')
        user = UserFactory(username='mia', email='Mia@acme.example')
        team_cycle = self.cycle('Tom', peer=(1, 3), email=True)
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=manager, row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=team_cycle.reviewee, row=1, col=0)
        other = self.cycle('Zoe')
        ask = ReviewerTokenFactory(cycle=other, category='peer', reviewer_email='mia@acme.example')
        ReviewerTokenFactory(cycle=other, category='peer', reviewer_email='mia@acme.example',
                             completed_at=self.now)  # answered: not listed

        state = dashboard.personal_state(user, self.org, 3, runs_team=False)

        self.assertEqual(state['to_review'], [ask])
        self.assertEqual([(row['cycle'], row['invited_answered'], row['invited']) for row in state['team']],
                         [(team_cycle, 1, 3)])
        self.assertEqual(state['own'], [])
