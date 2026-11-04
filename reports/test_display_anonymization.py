import copy

from django.test import SimpleTestCase

from .services import apply_display_anonymization, reviewer_counts


def _report_data(counts):
    """Stored report_data shape with one question and the given reviewer count per category."""
    scores = {'self': 4.0, 'peer': 3.5, 'manager': 3.0}
    return {
        'by_section': {
            '1': {'title': 'Craft', 'questions': {'10': {'by_category': {
                category: {'count': count, 'avg': scores[category]} for category, count in counts.items()
            }}}},
        },
        'section_summary': {'Craft': {category: scores[category] for category in counts}},
        'charts': {
            'section_scores': {'Craft': {**{category: scores[category] for category in counts}, 'others_avg': 3.25}},
            'overall': {**{category: scores[category] for category in counts}, 'others_avg': 3.25},
        },
        'insights': {'overall_sentiment': {'score': 3.25, 'self_avg': 4.0}},
    }


class SectionSummaryAnonymizationTests(SimpleTestCase):
    def test_section_summary_hides_peer_below_threshold(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1})

        summary = apply_display_anonymization(data, min_threshold=3)['section_summary']['Craft']

        self.assertTrue(summary['peer']['insufficient'])
        self.assertEqual(summary['peer']['message'], 'Insufficient responses (minimum 3 required)')
        self.assertEqual(summary['manager'], 3.0)
        self.assertEqual(summary['self'], 4.0)

    def test_section_summary_shows_peer_at_threshold(self):
        data = _report_data({'self': 1, 'peer': 3, 'manager': 1})

        summary = apply_display_anonymization(data, min_threshold=3)['section_summary']['Craft']

        self.assertEqual(summary['peer'], 3.5)

    def test_chart_series_drop_insufficient_categories(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1})

        charts = apply_display_anonymization(data, min_threshold=3)['charts']

        self.assertEqual(charts['section_scores'], {'Craft': {'self': 4.0, 'manager': 3.0, 'others_avg': 3.25}})
        self.assertEqual(charts['overall'], {'self': 4.0, 'manager': 3.0, 'others_avg': 3.25})

    def test_combined_values_unchanged(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1})
        original = copy.deepcopy(data)

        filtered = apply_display_anonymization(data, min_threshold=3)

        self.assertEqual(data, original)
        self.assertEqual(filtered['insights'], original['insights'])
        filtered['section_summary']['Craft']['peer'] = original['section_summary']['Craft']['peer']
        self.assertEqual(filtered['section_summary'], original['section_summary'])


class ReviewerCountsTests(SimpleTestCase):
    def test_reviewer_counts_is_max_count_per_category(self):
        data = _report_data({'self': 1, 'peer': 2})
        data['by_section']['1']['questions']['11'] = {'by_category': {'peer': {'count': 4}, 'manager': {'count': 1}}}
        data['by_section']['2'] = {'questions': {'20': {'by_category': {'peer': {'count': 3}}}}}

        self.assertEqual(reviewer_counts(data), {'self': 1, 'peer': 4, 'manager': 1})
