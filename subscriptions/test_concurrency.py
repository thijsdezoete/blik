"""Tests that need real row locks. Run with ./test.sh (PostgreSQL)."""
import threading
from unittest import skipUnless

from django.db import connection, connections
from django.test import TransactionTestCase

from accounts.factories import RevieweeFactory
from core.factories import OrganizationFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle
from subscriptions.testing import grant
from subscriptions.utils import NoCycleCredits, cycle_credits


def run_twice_at_once(fn):
    """Run fn in two threads released together; return results or raised exceptions."""
    barrier = threading.Barrier(2)
    results = []

    def worker():
        try:
            barrier.wait(timeout=5)
            results.append(fn())
        except Exception as exc:  # collected for assertions
            results.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


@skipUnless(connection.vendor == 'postgresql', 'row locks need PostgreSQL')
class LastCreditRaceTests(TransactionTestCase):
    # Restore migration-seeded rows after the table flush this test class causes.
    serialized_rollback = True

    def test_two_creations_for_the_last_credit_yield_one_cycle(self):
        org = OrganizationFactory()
        reviewee = RevieweeFactory(organization=org)
        questionnaire = QuestionnaireFactory(organization=org)
        grant(org, 1)

        results = run_twice_at_once(
            lambda: ReviewCycle.objects.create(reviewee=reviewee, questionnaire=questionnaire)
        )

        self.assertEqual(ReviewCycle.objects.filter(reviewee=reviewee).count(), 1)
        self.assertEqual(sum(isinstance(r, NoCycleCredits) for r in results), 1)
        self.assertEqual(cycle_credits(org), 0)
