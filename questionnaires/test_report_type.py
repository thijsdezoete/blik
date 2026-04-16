from django.test import TestCase

from core.factories import OrganizationFactory
from questionnaires.factories import (
    QuestionnaireFactory,
    QuestionSectionFactory,
    QuestionFactory,
)


class QuestionnaireReportTypeTestCase(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.questionnaire = QuestionnaireFactory(organization=self.org)
        self.section = QuestionSectionFactory(questionnaire=self.questionnaire)

    def _add_question(self, dreyfus_mapping):
        config = {'min': 1, 'max': 5}
        if dreyfus_mapping is not None:
            config['dreyfus_mapping'] = dreyfus_mapping
        QuestionFactory(section=self.section, config=config)

    def test_standard_360_when_no_mappings(self):
        self._add_question(None)
        self._add_question(None)
        self.assertEqual(self.questionnaire.report_type_label, "Standard 360")

    def test_dreyfus_skill_only(self):
        self._add_question({'skill': 1.5})
        self._add_question(None)
        self.assertEqual(self.questionnaire.report_type_label, "Dreyfus (Skill)")

    def test_dreyfus_agency_only(self):
        self._add_question({'agency': 1.5})
        self.assertEqual(self.questionnaire.report_type_label, "Dreyfus (Agency)")

    def test_dreyfus_skill_and_agency(self):
        self._add_question({'skill': 1.5})
        self._add_question({'agency': 0.5})
        self.assertEqual(self.questionnaire.report_type_label, "Dreyfus (Skill + Agency)")

    def test_dreyfus_combined_in_single_question(self):
        self._add_question({'skill': 1.0, 'agency': 0.5})
        self.assertEqual(self.questionnaire.report_type_label, "Dreyfus (Skill + Agency)")

    def test_zero_weights_are_ignored(self):
        self._add_question({'skill': 0, 'agency': 0})
        self.assertEqual(self.questionnaire.report_type_label, "Standard 360")

    def test_malformed_mapping_is_ignored(self):
        self._add_question("not-a-dict")
        self.assertEqual(self.questionnaire.report_type_label, "Standard 360")
