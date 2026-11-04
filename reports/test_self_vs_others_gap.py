from django.test import TestCase

from .services import REPORT_SCHEMA, self_vs_others_gap


def _report_data(self_avg, others_score, counts):
    """Stored report_data shape: overall_sentiment plus per-category counts."""
    return {
        'insights': {
            'overall_sentiment': {'score': others_score, 'self_avg': self_avg},
        },
        'by_section': {
            '1': {'questions': {'10': {'by_category': {
                category: {'count': count} for category, count in counts.items()
            }}}},
        },
    }


class SelfVsOthersGapTests(TestCase):
    def test_no_gap_without_self_assessment(self):
        data = _report_data(None, 3.5, {'peer': 3, 'manager': 1})
        self.assertIsNone(self_vs_others_gap(data, min_threshold=3))

    def test_no_gap_without_others_score(self):
        data = _report_data(4.0, None, {'self': 1})
        data['insights']['overall_sentiment'] = None
        self.assertIsNone(self_vs_others_gap(data, min_threshold=3))

    def test_no_gap_for_old_report_without_insights(self):
        self.assertIsNone(self_vs_others_gap({'by_section': {}}, min_threshold=3))

    def test_no_gap_below_anonymity_threshold_self_not_counted(self):
        data = _report_data(4.0, 3.0, {'self': 1, 'peer': 2})
        self.assertIsNone(self_vs_others_gap(data, min_threshold=3))
        self.assertEqual(self_vs_others_gap(data, min_threshold=2), 1.0)

    def test_peers_and_manager_count_together(self):
        data = _report_data(4.0, 3.0, {'self': 1, 'peer': 3, 'manager': 1})
        self.assertEqual(self_vs_others_gap(data, min_threshold=3), 1.0)

    def test_reviewer_count_is_max_per_question_not_sum(self):
        data = _report_data(4.0, 3.0, {'self': 1, 'peer': 2})
        data['by_section']['1']['questions']['11'] = {'by_category': {'peer': {'count': 2}}}
        self.assertIsNone(self_vs_others_gap(data, min_threshold=3))

    def test_positive_when_self_rates_higher(self):
        data = _report_data(4.5, 3.25, {'self': 1, 'peer': 3})
        self.assertEqual(self_vs_others_gap(data, min_threshold=3), 1.25)

    def test_negative_when_self_rates_lower(self):
        data = _report_data(2.5, 4.0, {'self': 1, 'peer': 3})
        self.assertEqual(self_vs_others_gap(data, min_threshold=3), -1.5)


class HiddenGroupGapTests(TestCase):
    def test_gap_leaves_out_hidden_group(self):
        # Manager 3.0 and two peers 5.0: the stored combined score is 4.33, the peers are hidden at threshold 3
        data = {
            'schema': REPORT_SCHEMA,
            'by_section': {'1': {'title': 'Craft', 'questions': {'10': {'question_type': 'rating', 'by_category': {
                'self': {'count': 1, 'avg': 4.0}, 'manager': {'count': 1, 'avg': 3.0}, 'peer': {'count': 2, 'avg': 5.0},
            }}}}},
            'section_summary': {'Craft': {'self': 4.0, 'manager': 3.0, 'peer': 5.0}},
            'charts': {'overall': {'self': 4.0, 'manager': 3.0, 'peer': 5.0, 'others_avg': 4.33}},
            'insights': {'overall_sentiment': {'score': 4.33, 'self_avg': 4.0}},
        }

        self.assertEqual(self_vs_others_gap(data, min_threshold=3), 1.0)
        self.assertEqual(self_vs_others_gap(data, min_threshold=2), -0.33)
