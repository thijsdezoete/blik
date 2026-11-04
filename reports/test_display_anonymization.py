import copy

from django.test import SimpleTestCase, TestCase

from reviews.templatetags.feedback_tags import others_average

from .services import REPORT_SCHEMA, apply_display_anonymization, reviewer_counts

SCORES = {'self': 4.0, 'peer': 2.0, 'manager': 2.8, 'direct_report': 3.6}


def _report_data(counts, schema=REPORT_SCHEMA):
    """Stored report_data with one rating question, the given reviewer count per category, and its derived values."""
    data = {
        'by_section': {
            '1': {'title': 'Craft', 'questions': {'10': {'question_type': 'rating', 'by_category': {
                category: {'count': count, 'avg': SCORES[category]} for category, count in counts.items()
            }}}},
        },
        'section_summary': {'Craft': {category: SCORES[category] for category in counts}},
        'charts': {
            'section_scores': {'Craft': {**{category: SCORES[category] for category in counts}, 'others_avg': 3.0}},
            'overall': {**{category: SCORES[category] for category in counts}, 'others_avg': 3.0},
        },
        'insights': {
            'overall_sentiment': {'score': 2.6, 'rating': 'needs_support', 'based_on': 'others', 'self_avg': 4.0},
            'perception_gaps': [{'type': 'overconfidence', 'others_score': 2.6}],
            'strengths': [],
            'development_areas': [{'area': 'Craft', 'others_avg': 2.6}],
            'skill_profile': {'skill_level': 3.0},
        },
        'peer_benchmarks': {'Craft': {'current_score': 2.6, 'peer_median': 3.0}},
        'comparison': {
            'has_previous': True, 'show_trends': True,
            'overall_trend': {'direction': 'down', 'change': -0.4},
            'section_trends': {'Craft': {'direction': 'down', 'change': -0.4}},
        },
    }
    if schema:
        data['schema'] = schema
    return data


class SectionSummaryAnonymizationTests(TestCase):
    def test_section_summary_hides_peer_below_threshold(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1})

        summary = apply_display_anonymization(data, min_threshold=3)['section_summary']

        self.assertEqual(summary, {'Craft': {
            'self': 4.0,
            'peer': {'insufficient': True, 'message': 'Insufficient responses (minimum 3 required)'},
            'manager': 2.8,
        }})

    def test_section_summary_shows_peer_at_threshold(self):
        data = _report_data({'self': 1, 'peer': 3, 'manager': 1})

        summary = apply_display_anonymization(data, min_threshold=3)['section_summary']['Craft']

        self.assertEqual(summary['peer'], 2.0)

    def test_chart_series_drop_insufficient_categories(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1})

        charts = apply_display_anonymization(data, min_threshold=3)['charts']

        self.assertNotIn('peer', charts['section_scores']['Craft'])
        self.assertNotIn('peer', charts['overall'])
        self.assertEqual(charts['overall']['manager'], 2.8)

    def test_second_non_exempt_group_is_hidden_too(self):
        data = _report_data({'self': 1, 'peer': 3, 'direct_report': 2})

        filtered = apply_display_anonymization(data, min_threshold=3)

        self.assertTrue(filtered['section_summary']['Craft']['direct_report']['insufficient'])
        self.assertEqual(filtered['section_summary']['Craft']['peer'], 2.0)
        self.assertEqual(filtered['charts']['overall'], {'self': 4.0, 'peer': 2.0, 'others_avg': 2.0})

    def test_missing_or_empty_derived_values(self):
        for value in (None, {}):
            data = _report_data({'self': 1, 'peer': 2, 'manager': 1})
            data['section_summary'] = value
            data['charts'] = value
            del data['comparison']

            filtered = apply_display_anonymization(data, min_threshold=3)

            self.assertEqual(filtered['section_summary'], value)
            self.assertEqual(filtered['charts']['overall']['manager'], 2.8)


class CombinedValuesAnonymizationTests(TestCase):
    def test_hidden_group_not_derivable_from_combined_values(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1})

        filtered = apply_display_anonymization(data, min_threshold=3)

        manager = SCORES['manager']
        self.assertEqual(filtered['charts']['section_scores']['Craft']['others_avg'], manager)
        self.assertEqual(filtered['charts']['overall']['others_avg'], manager)
        self.assertEqual(others_average(filtered['section_summary']['Craft']), manager)
        insights = filtered['insights']
        self.assertEqual(insights['overall_sentiment']['score'], manager)
        self.assertEqual(insights['overall_sentiment']['self_avg'], SCORES['self'])
        self.assertEqual([gap['others_score'] for gap in insights['perception_gaps']], [manager])
        self.assertEqual([area['others_avg'] for area in insights['development_areas']], [manager])

    def test_no_hidden_groups_numbers_unchanged(self):
        data = _report_data({'self': 1, 'peer': 3, 'manager': 1})

        self.assertEqual(apply_display_anonymization(data, min_threshold=3), data)

    def test_only_hidden_contributors_leaves_combined_absent(self):
        data = _report_data({'self': 1, 'peer': 2})

        filtered = apply_display_anonymization(data, min_threshold=3)

        self.assertNotIn('others_avg', filtered['charts']['section_scores']['Craft'])
        self.assertNotIn('others_avg', filtered['charts']['overall'])
        self.assertEqual(others_average(filtered['section_summary']['Craft']), 0)
        self.assertIsNone(filtered['insights']['overall_sentiment'])
        self.assertEqual(filtered['insights']['perception_gaps'], [])
        self.assertEqual(filtered['insights']['development_areas'], [])

    def test_hidden_group_leaves_out_benchmarks_and_trends(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1})

        filtered = apply_display_anonymization(data, min_threshold=3)

        self.assertNotIn('peer_benchmarks', filtered)
        self.assertEqual(filtered['comparison'], {'has_previous': True, 'show_trends': True})

    def test_old_report_leaves_out_combined_insights(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1}, schema=None)

        filtered = apply_display_anonymization(data, min_threshold=3)

        self.assertEqual(filtered['insights'], {
            'overall_sentiment': None, 'perception_gaps': [], 'strengths': [], 'development_areas': [],
            'skill_profile': {'skill_level': 3.0},
        })
        self.assertEqual(filtered['section_summary']['Craft']['manager'], 2.8)
        self.assertEqual(filtered['charts']['overall']['manager'], 2.8)

    def test_input_is_not_changed(self):
        data = _report_data({'self': 1, 'peer': 2, 'manager': 1})
        original = copy.deepcopy(data)

        apply_display_anonymization(data, min_threshold=3)

        self.assertEqual(data, original)


class ReviewerCountsTests(SimpleTestCase):
    def test_reviewer_counts_is_max_count_per_category(self):
        data = _report_data({'self': 1, 'peer': 2})
        data['by_section']['1']['questions']['11'] = {'by_category': {'peer': {'count': 4}, 'manager': {'count': 1}}}
        data['by_section']['2'] = {'questions': {'20': {'by_category': {'peer': {'count': 3}}}}}

        self.assertEqual(reviewer_counts(data), {'self': 1, 'peer': 4, 'manager': 1})


class OthersAverageTests(SimpleTestCase):
    def test_skips_self_and_hidden_groups(self):
        categories = {'self': 5.0, 'peer': {'insufficient': True}, 'manager': 3.0, 'direct_report': 4.0}

        self.assertEqual(others_average(categories), 3.5)
