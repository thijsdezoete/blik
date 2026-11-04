from django.test import SimpleTestCase

from .services import REPORT_SCHEMA, self_vs_others_gap


def _report_data(self_avg, others_score, counts):
    """Stored report_data shape: one rating question with an average and count per category."""
    averages = {'self': self_avg}
    return {
        'by_section': {
            '1': {'title': 'Craft', 'questions': {'10': {'question_type': 'rating', 'by_category': {
                category: {'count': count, 'avg': averages.get(category, others_score)}
                for category, count in counts.items()
            }}}},
        },
    }


class SelfVsOthersGapTests(SimpleTestCase):
    def test_no_gap_without_self_assessment(self):
        data = _report_data(None, 3.5, {'peer': 3, 'manager': 1})
        self.assertIsNone(self_vs_others_gap(data, min_threshold=3))

    def test_no_gap_without_others_score(self):
        data = _report_data(4.0, None, {'self': 1})
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
        data['by_section']['1']['questions']['11'] = {'question_type': 'rating', 'by_category': {'peer': {'count': 2, 'avg': 3.0}}}
        self.assertIsNone(self_vs_others_gap(data, min_threshold=3))

    def test_positive_when_self_rates_higher(self):
        data = _report_data(4.5, 3.25, {'self': 1, 'peer': 3})
        self.assertEqual(self_vs_others_gap(data, min_threshold=3), 1.25)

    def test_negative_when_self_rates_lower(self):
        data = _report_data(2.5, 4.0, {'self': 1, 'peer': 3})
        self.assertEqual(self_vs_others_gap(data, min_threshold=3), -1.5)


class HiddenGroupGapTests(SimpleTestCase):
    def test_gap_leaves_out_hidden_group(self):
        # Manager 3.0 and two peers 5.0: the peers are hidden at threshold 3
        data = {
            'schema': REPORT_SCHEMA,
            'by_section': {'1': {'title': 'Craft', 'questions': {'10': {'question_type': 'rating', 'by_category': {
                'self': {'count': 1, 'avg': 4.0}, 'manager': {'count': 1, 'avg': 3.0}, 'peer': {'count': 2, 'avg': 5.0},
            }}}}},
        }

        self.assertEqual(self_vs_others_gap(data, min_threshold=3), 1.0)
        self.assertEqual(self_vs_others_gap(data, min_threshold=2), 0.0)
