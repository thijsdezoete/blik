from django.test import TestCase

from accounts.factories import RevieweeFactory
from accounts.import_service import import_reports, import_review_cycles
from core.factories import OrganizationFactory
from questionnaires.factories import QuestionnaireFactory
from reports.finalize import cycles_to_finalize
from reviews.models import ReviewCycle


class ImportedCycleFinalisationTests(TestCase):
    """Imported cycles are history: the finalize_reports cron must never email their reviewees."""

    def setUp(self):
        self.org = OrganizationFactory()
        self.questionnaire = QuestionnaireFactory(organization=self.org)
        self.reviewee = RevieweeFactory(organization=self.org, name='Anna')

    def test_imported_completed_cycle_is_finalized(self):
        import_review_cycles(self.org, [{
            'reviewee': 'Anna', 'questionnaire': self.questionnaire.name, 'status': 'completed',
        }], {})

        cycle = ReviewCycle.objects.get(reviewee=self.reviewee)
        self.assertIsNotNone(cycle.report_finalized_at)
        self.assertNotIn(cycle, cycles_to_finalize())

    def test_imported_active_cycle_is_not_finalized(self):
        import_review_cycles(self.org, [{'reviewee': 'Anna', 'questionnaire': self.questionnaire.name}], {})

        self.assertIsNone(ReviewCycle.objects.get(reviewee=self.reviewee).report_finalized_at)

    def test_cycle_created_for_an_imported_report_is_finalized(self):
        import_reports(self.org, [{
            'reviewee': 'Anna', 'questionnaire_name': self.questionnaire.name, 'report_data': {},
        }], {})

        cycle = ReviewCycle.objects.get(reviewee=self.reviewee)
        self.assertIsNotNone(cycle.report_finalized_at)
        self.assertNotIn(cycle, cycles_to_finalize())
