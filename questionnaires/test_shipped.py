"""The questionnaires made from a shipped template get {name} and the shipped translations, but edited texts do not."""
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from accounts.import_service import import_questionnaires
from accounts.services import export_organization_data
from core.models import Organization
from questionnaires.legacy_config import move_all_texts_out_of_config
from questionnaires.models import Questionnaire, QuestionnaireTranslation
from questionnaires.shipped import add_shipped_translations, get_template_texts
from questionnaires.signals import clone_questionnaire_for_organization
from questionnaires.translations import get_language_states, get_text_translations

GERMAN = {
    ('simple', '360 Degree Feedback'): '360°-Feedback',
    ('simple', 'Technical Skills'): 'Fachliche Fähigkeiten',
    ('simple', 'Exceptional'): 'Herausragend',
    ('simple', '{name} communicates clearly and effectively'): '{name} kommuniziert klar und wirkungsvoll',
    ('simple', 'Agree'): 'Stimme zu',
    ('simple', 'Any additional comments?'): 'Haben Sie weitere Anmerkungen?',
}
INFORMAL = {
    ('simple', 'Any additional comments?'): 'Hast du weitere Anmerkungen?',
}


class Catalog:
    """A compiled catalog holding the given translations by template key and English text."""

    def __init__(self, texts):
        self.texts = texts

    def pgettext(self, context, message):
        return self.texts.get((context, message))


@patch('questionnaires.shipped.get_catalogs', lambda: {'de': Catalog(GERMAN), 'de-informal': Catalog(INFORMAL)})
class ShippedTranslationsTest(TestCase):
    """The template "360 Degree Feedback" as the migrations create it, and its copy in an organization."""

    def setUp(self):
        move_all_texts_out_of_config()
        self.organization = Organization.objects.create(name='Acme', email='org@acme.example')
        self.copy = Questionnaire.objects.get(organization=self.organization, name='360 Degree Feedback')

    def get_section(self, title):
        return self.copy.sections.get(title=title)

    def get_question(self, text):
        return self.copy.sections.get(questions__question_text=text).questions.get(question_text=text)

    def test_questionnaires_get_the_key_of_the_template_with_their_name(self):
        renamed = Questionnaire.objects.get(organization=self.organization, name='Manager 360 Review')
        renamed.name = 'Leadership'
        renamed.save()

        add_shipped_translations()

        template = Questionnaire.objects.templates().get(name='360 Degree Feedback')
        self.copy.refresh_from_db()
        renamed.refresh_from_db()
        template_keys = [template.template_key, self.copy.template_key, renamed.template_key]
        self.assertEqual(template_keys, ['simple', 'simple', ''])

    def test_a_copy_keeps_the_template_key(self):
        self.copy.template_key = 'simple'
        self.copy.save()

        other = Organization.objects.create(name='Other', email='org@other.example')

        self.assertEqual(clone_questionnaire_for_organization(self.copy, other).template_key, 'simple')

    def test_this_person_becomes_the_placeholder_where_the_text_is_the_templates(self):
        unchanged = self.get_question('{name} communicates clearly and effectively')
        unchanged.question_text = 'This person communicates clearly and effectively'
        unchanged.save()
        edited = self.get_question('{name} is flexible and adapts well to change')
        edited.question_text = 'This person adapts to change'
        edited.save()

        add_shipped_translations()

        unchanged.refresh_from_db()
        edited.refresh_from_db()
        self.assertEqual(unchanged.question_text, '{name} communicates clearly and effectively')
        self.assertEqual(edited.question_text, 'This person adapts to change')

    def test_the_texts_the_catalog_translates_are_translated_and_current(self):
        add_shipped_translations()

        questionnaire = self.copy.translated('de')
        technical, collaboration, approach, overall = questionnaire.sections.all()
        problem_solving, code_quality, expertise = technical.questions.all()
        teamwork, communication, mentoring = collaboration.questions.all()
        texts = get_text_translations(self.copy, 'de')

        self.assertEqual((questionnaire.name, technical.title), ('360°-Feedback', 'Fachliche Fähigkeiten'))
        self.assertEqual(problem_solving.labels['5'], 'Herausragend')
        self.assertEqual(communication.question_text, '{name} kommuniziert klar und wirkungsvoll')
        self.assertEqual([option.label for option in communication.options.all()], [
            'Strongly Disagree', 'Disagree', 'Neutral', 'Stimme zu', 'Strongly Agree'])
        self.assertEqual(sum(bool(text.text) for text in texts), 7)
        self.assertFalse(any(text.outdated for text in texts))

    def test_an_edited_text_is_not_translated(self):
        section = self.get_section('Technical Skills')
        section.title = 'Engineering'
        section.save()

        add_shipped_translations()

        self.assertFalse(section.translations.exists())

    def test_a_part_translated_into_a_language_keeps_its_translation(self):
        QuestionnaireTranslation.objects.create(questionnaire=self.copy, language='de', name='Unser Feedback')

        add_shipped_translations()

        [translation] = self.copy.translations.all()
        self.assertEqual((translation.name, translation.source_checksums), ('Unser Feedback', {}))

    def test_a_second_run_changes_nothing(self):
        add_shipped_translations()
        translations = list(QuestionnaireTranslation.objects.values())

        add_shipped_translations()

        self.assertEqual(list(QuestionnaireTranslation.objects.values()), translations)

    def test_a_variant_gets_only_its_own_texts(self):
        add_shipped_translations()

        question = self.get_question('Any additional comments?')
        [translation] = question.translations.filter(language='de-informal')
        questionnaire = self.copy.translated('de-informal')

        self.assertEqual(translation.question_text, 'Hast du weitere Anmerkungen?')
        self.assertFalse(self.copy.translations.filter(language='de-informal').exists())
        self.assertEqual(questionnaire.name, '360°-Feedback')

    def test_a_questionnaire_in_another_source_language_is_left_alone(self):
        self.copy.source_language = 'de'
        self.copy.save()

        add_shipped_translations()

        self.assertFalse(self.copy.translations.exists())

    def test_export_and_import_keep_the_template_key(self):
        add_shipped_translations()
        data = json.loads(json.dumps(export_organization_data(self.organization)))
        [questionnaire_data] = [item for item in data['questionnaires'] if item['name'] == '360 Degree Feedback']
        unknown = {**questionnaire_data, 'name': 'Unknown', 'template_key': 'unknown'}
        wrong_type = {**questionnaire_data, 'name': 'Wrong type', 'template_key': ['simple']}
        other = Organization.objects.create(name='Other', email='org@other.example')
        Questionnaire.objects.filter(organization=other).delete()

        result = import_questionnaires(other, [questionnaire_data, unknown, wrong_type])

        imported = result['questionnaire_map']
        template_keys = [imported[name].template_key for name in ['360 Degree Feedback', 'Unknown', 'Wrong type']]
        self.assertEqual(questionnaire_data['template_key'], 'simple')
        self.assertEqual(template_keys, ['simple', '', ''])


class TemplateCatalogueTest(TestCase):

    def test_the_catalogue_template_holds_every_text_of_a_template_once(self):
        texts = get_template_texts('simple')

        self.assertEqual(texts[:3], [
            '360 Degree Feedback',
            'Comprehensive 360 degree feedback questionnaire for professional development',
            'Technical Skills',
        ])
        self.assertIn('Exceptional', texts)
        self.assertEqual(texts.count('Strongly Agree'), 1)


class ShippedCatalogTest(TestCase):
    """The compiled catalogues in locale/, as the upgrade reads them."""

    def test_the_upgrade_translates_every_text_of_every_template_into_german(self):
        call_command('upgrade', stdout=StringIO())

        for template in Questionnaire.objects.templates():
            states = {state.code: state for state in get_language_states(template)}
            # French and Italian currently ship interface translations only.
            for language in ('de', 'de-informal'):
                state = states[language]
                self.assertEqual((state.missing, state.outdated), (0, 0), f'{template.name}, {state.code}')
