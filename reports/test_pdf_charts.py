from django.test import SimpleTestCase

from reports.pdf_charts import radar_chart, self_vs_others_bars


class RadarChartTests(SimpleTestCase):
    def test_radar_point_for_score_5_on_first_axis_is_straight_up(self):
        chart = radar_chart({'A': {'peer': 5.0}, 'B': {'peer': 5.0}, 'C': {'peer': 5.0}}, size=200)
        x, y = chart['others'].split(' ')[0].split(',')
        self.assertAlmostEqual(float(x), 100)
        self.assertAlmostEqual(float(y), 100 - 76)

    def test_radar_without_self_has_no_self_polygon(self):
        chart = radar_chart({'A': {'peer': 4}, 'B': {'manager': 3}, 'C': {'peer': 2}})
        self.assertIsNone(chart['self'])
        self.assertEqual(len(chart['rings']), 5)
        self.assertEqual(len(chart['axes']), 3)

    def test_radar_single_section(self):
        chart = radar_chart({'Only': {'self': 3, 'peer': 4}})
        self.assertEqual(len(chart['axes']), 1)
        self.assertTrue(chart['others'])
        self.assertTrue(chart['self'])

    def test_radar_section_without_others_counts_as_zero(self):
        chart = radar_chart({'A': {'self': 3}, 'B': {'peer': 4}}, size=200)
        self.assertEqual(chart['others'].split(' ')[0], '100.0,100.0')

    def test_radar_truncates_long_labels(self):
        chart = radar_chart({'x' * 40: {'peer': 3}})
        self.assertEqual(len(chart['axes'][0]['label']), 22)
        self.assertTrue(chart['axes'][0]['label'].endswith('…'))

    def test_radar_wraps_labels_on_two_lines(self):
        chart = radar_chart({'Industry Fit & Problem Solving': {'peer': 3}, 'B': {'peer': 3}, 'C': {'peer': 3}})
        self.assertEqual(chart['axes'][0]['lines'], ['Industry Fit &', 'Problem Solving'])
        self.assertEqual(chart['axes'][1]['lines'], ['B'])

    def test_radar_cuts_the_second_line_short(self):
        chart = radar_chart({'Knowledge Sharing & Mentorship of the whole team': {'peer': 3}})
        first, second = chart['axes'][0]['lines']
        self.assertEqual(first, 'Knowledge Sharing')
        self.assertEqual(len(second), 18)
        self.assertTrue(second.endswith('…'))


class SelfVsOthersBarsTests(SimpleTestCase):
    def test_others_is_the_group_mean_not_the_stored_others_avg(self):
        bars = self_vs_others_bars({'A': {'self': 3, 'peer': 4, 'manager': 2, 'others_avg': 5}})
        self.assertEqual(bars[0]['others'], 3.0)

    def test_bars_scale_to_width(self):
        bars = self_vs_others_bars(
            {'A': {'self': 5, 'peer': 2, 'manager': 4}, 'B': {'self': 2.5}}, width=480)
        full = 480 - 120
        self.assertEqual(bars[0]['others'], 3.0)
        self.assertAlmostEqual(bars[0]['others_w'], 3 / 5 * full)
        self.assertAlmostEqual(bars[0]['self_w'], full)
        self.assertIsNone(bars[1]['others'])
        self.assertEqual(bars[1]['others_w'], 0)
        self.assertAlmostEqual(bars[1]['self_w'], full / 2)


class SvgPartialTests(SimpleTestCase):
    def test_partials_render_dot_decimals_in_any_locale(self):
        from django.template.loader import render_to_string
        from django.utils import translation
        data = {'A': {'self': 3.3, 'peer': 4.1}, 'B': {'peer': 2.2}}
        with translation.override('de'):
            radar = render_to_string('reports/pdf/_radar.svg.html', {'radar': radar_chart(data)})
            bars = render_to_string('reports/pdf/_self_vs_others.svg.html',
                                    {'bars': self_vs_others_bars(data), 'width': 480})
        for svg in (radar, bars):
            self.assertIn('<svg', svg)
            self.assertNotRegex(svg, r'(?:x|y|width|x2|y2)="[^"]*,')
        self.assertIn('viewBox="-90 -34 420 308"', radar)
