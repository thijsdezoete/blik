import re

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from reports.templatetags.diagram_tags import stage_opacity


def groups(html, prefix, number):
    # Every group whose id contains cp_N / sy_N: root groups and the nested ones, as the web CSS selects them.
    return re.findall(rf'<g id="[^"]*{prefix}_{number}[^"]*"([^>]*)>', html)


def label_fill(html, label_id):
    return re.search(rf'<g id="{label_id}[^"]*-fill-merged"[^>]*fill="([^"]*)"', html)[1]


class StageOpacityTests(SimpleTestCase):
    def test_current_stage_and_no_stage_stay_full_strength(self):
        self.assertEqual(stage_opacity(4, 'proficient'), '')
        self.assertEqual(stage_opacity(2, '2'), '')
        self.assertEqual(stage_opacity(1, ''), '')
        self.assertEqual(stage_opacity(1, None), '')

    def test_other_stages_fade(self):
        self.assertEqual(stage_opacity(3, 'proficient'), ' opacity="0.3"')
        self.assertEqual(stage_opacity(5, '4'), ' opacity="0.3"')


class DiagramHighlightTests(SimpleTestCase):
    def test_dreyfus_svg_fades_other_stages(self):
        html = render_to_string('components/dreyfus_model_svg.html', {'current_stage': 'proficient'})
        for n in (1, 2, 3, 5):
            found = groups(html, 'cp', n)
            self.assertGreater(len(found), 2)
            for attrs in found:
                self.assertRegex(attrs, r'(?<!-)opacity="0.3"')
        for attrs in groups(html, 'cp', 4):
            self.assertNotRegex(attrs, r'(?<!-)opacity=')
        self.assertEqual(label_fill(html, 'tx_proficie_'), '#3b82f6')
        self.assertEqual(label_fill(html, 'tx_novice_'), 'var(--text-primary)')

    def test_dreyfus_svg_without_stage_fades_nothing(self):
        html = render_to_string('components/dreyfus_model_svg.html', {})
        self.assertNotIn('opacity="0.3"', html)
        self.assertNotIn('#3b82f6', html)

    def test_agency_svg_fades_other_levels(self):
        html = render_to_string('components/agency_levels_svg.html', {'current_level': '4'})
        # Group numbering is reversed: sy_2 is level 4.
        for attrs in groups(html, 'sy', 2):
            self.assertNotRegex(attrs, r'(?<!-)opacity=')
        for n in (1, 3, 4, 5):
            found = groups(html, 'sy', n)
            self.assertGreater(len(found), 3)
            for attrs in found:
                self.assertRegex(attrs, r'(?<!-)opacity="0.3"')
        self.assertEqual(label_fill(html, 'tx_solution_1hfpjkb'), '#3b82f6')

    def test_agency_svg_without_level_fades_nothing(self):
        html = render_to_string('components/agency_levels_svg.html', {})
        self.assertNotIn('opacity="0.3"', html)
