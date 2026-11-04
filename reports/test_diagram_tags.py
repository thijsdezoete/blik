import re

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from reports.templatetags.diagram_tags import stage_opacity


def root_groups(html, prefix, number):
    return re.findall(rf'<g id="g-root-{prefix}_{number}_[^"]*"([^>]*)>', html)


def label_fill(html, label_id):
    return re.search(rf'<g id="{label_id}[^"]*-fill-merged"[^>]*fill="([^"]*)"', html)[1]


class StageOpacityTests(SimpleTestCase):
    def test_current_stage_and_no_stage_stay_full_strength(self):
        self.assertEqual(stage_opacity(4, 'proficient'), '')
        self.assertEqual(stage_opacity(2, '2'), '')
        self.assertEqual(stage_opacity(1, ''), '')
        self.assertEqual(stage_opacity(1, None), '')

    def test_other_stages_fade(self):
        self.assertEqual(stage_opacity(3, 'proficient'), '0.3')
        self.assertEqual(stage_opacity(5, '4'), '0.3')


class DiagramHighlightTests(SimpleTestCase):
    def test_dreyfus_svg_fades_other_stages(self):
        html = render_to_string('components/dreyfus_model_svg.html', {'current_stage': 'proficient'})
        for n in (1, 2, 3, 5):
            groups = root_groups(html, 'cp', n)
            self.assertTrue(groups)
            for attrs in groups:
                self.assertIn('opacity="0.3"', attrs)
        for attrs in root_groups(html, 'cp', 4):
            self.assertNotIn('opacity', attrs)
        self.assertEqual(label_fill(html, 'tx_proficie_'), '#3b82f6')
        self.assertEqual(label_fill(html, 'tx_novice_'), '#111827')
        self.assertNotIn('var(--text-primary)', html)

    def test_dreyfus_svg_without_stage_fades_nothing(self):
        html = render_to_string('components/dreyfus_model_svg.html', {})
        self.assertNotIn('opacity="0.3"', html)
        self.assertNotIn('#3b82f6', html)

    def test_agency_svg_fades_other_levels(self):
        html = render_to_string('components/agency_levels_svg.html', {'current_level': '4'})
        # Group numbering is reversed: sy_2 is level 4.
        for attrs in root_groups(html, 'sy', 2):
            self.assertNotIn('opacity', attrs)
        for n in (1, 3, 4, 5):
            groups = root_groups(html, 'sy', n)
            self.assertTrue(groups)
            for attrs in groups:
                self.assertIn('opacity="0.3"', attrs)
        self.assertEqual(label_fill(html, 'tx_solution_1hfpjkb'), '#3b82f6')
        self.assertNotIn('var(--text-primary)', html)

    def test_agency_svg_without_level_fades_nothing(self):
        html = render_to_string('components/agency_levels_svg.html', {})
        self.assertNotIn('opacity="0.3"', html)
