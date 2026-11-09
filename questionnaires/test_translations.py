"""Questionnaires are translated text by text; whatever is not translated shows in the source language."""
import json

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import translation
from rest_framework.test import APIClient

from accounts.import_service import import_questionnaires
from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from accounts.services import export_organization_data
from api.models import APIToken
from core.models import Organization
from questionnaires.answer_options import DEFAULT_LIKERT_SCALE, save_options
from questionnaires.models import (
    AnswerOptionTranslation,
    Question,
    QuestionSection,
    QuestionSectionTranslation,
    QuestionTranslation,
    Questionnaire,
    QuestionnaireTranslation,
)
from questionnaires.signals import clone_questionnaire_for_organization
from questionnaires.translations import get_checksum, get_text_translations, save_text_translations
from reviews.models import ReviewCycle, ReviewerToken
from reviews.outbox import queue_invitations, send_queued_emails


class TranslatedQuestionnaireTestCase(TestCase):
    """An English questionnaire, partly translated into German, and its section title also into informal German."""

    def setUp(self):
        ensure_permission_groups()
        self.organization = Organization.objects.create(name='Acme', email='org@acme.example')
        self.admin = User.objects.create_user('admin', 'admin@acme.example', 'pw')
        UserProfile.objects.create(user=self.admin, organization=self.organization)
        assign_organization_admin(self.admin)
        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=self.organization)
        self.section = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Your growth')
        self.rating = Question.objects.create(
            section=self.section,
            question_text='Shares knowledge',
            question_type='rating',
            config={'min': 1, 'max': 5},
            labels={'1': 'Poor', '5': 'Excellent'},
            action_items=[{'key': 'pairing', 'text': 'Pair weekly', 'threshold': 3.5}],
            order=0,
        )
        self.likert = Question.objects.create(
            section=self.section,
            question_text='Listens well',
            question_type='likert',
            order=1,
        )
        save_options(self.likert, [(None, 'Agree', None), (None, 'Disagree', None)])
        agree, disagree = self.likert.options.all()

        QuestionnaireTranslation.objects.create(questionnaire=self.questionnaire, language='de', name='Fähigkeiten')
        QuestionSectionTranslation.objects.create(section=self.section, language='de', title='Ihr Wachstum')
        QuestionSectionTranslation.objects.create(section=self.section, language='de-informal', title='Dein Wachstum')
        QuestionTranslation.objects.create(
            question=self.rating,
            language='de',
            question_text='Teilt Wissen',
            labels={'1': 'Schwach', '9': 'Ohne Gegenstück'},
            action_items={'pairing': 'Wöchentlich zu zweit arbeiten'},
        )
        AnswerOptionTranslation.objects.create(option=agree, language='de', label='Stimme zu')

        self.reviewee = Reviewee.objects.create(name='Dana', email='dana@acme.example', organization=self.organization)
        self.cycle = ReviewCycle.objects.create(reviewee=self.reviewee, questionnaire=self.questionnaire)


class TranslatedCopyTest(TranslatedQuestionnaireTestCase):

    def test_the_copy_has_the_translations_and_the_source_texts_for_the_rest(self):
        questionnaire = self.questionnaire.translated('de')
        [section] = questionnaire.sections.all()
        rating, likert = section.questions.all()
        [action_item] = rating.action_items

        self.assertEqual((questionnaire.name, questionnaire.description), ('Fähigkeiten', ''))
        self.assertEqual(section.title, 'Ihr Wachstum')
        self.assertEqual(rating.question_text, 'Teilt Wissen')
        self.assertEqual(rating.labels, {'1': 'Schwach', '5': 'Excellent'})
        self.assertEqual(action_item['text'], 'Wöchentlich zu zweit arbeiten')
        self.assertEqual(action_item['threshold'], 3.5)
        self.assertEqual(likert.question_text, 'Listens well')
        self.assertEqual([option.label for option in likert.options.all()], ['Stimme zu', 'Disagree'])
        self.assertEqual(likert.options.count(), 2)

    def test_rating_descriptions_are_translated_by_value(self):
        self.rating.descriptions = {'1': 'Often late', '5': 'Always on time'}
        self.rating.save()
        self.rating.translations.filter(language='de').update(descriptions={'1': 'Oft zu spät', '9': 'Verwaist'})

        [section] = self.questionnaire.translated('de').sections.all()
        rating, likert = section.questions.all()

        self.assertEqual(rating.descriptions, {'1': 'Oft zu spät', '5': 'Always on time'})

    def test_a_variant_takes_its_own_texts_and_those_of_its_base_language(self):
        [section] = self.questionnaire.translated('de-informal').sections.all()
        rating, likert = section.questions.all()

        self.assertEqual(section.title, 'Dein Wachstum')
        self.assertEqual(rating.question_text, 'Teilt Wissen')

    def test_without_a_language_the_active_one_counts(self):
        with translation.override('de'):
            questionnaire = self.questionnaire.translated()

        self.assertEqual(questionnaire.name, 'Fähigkeiten')

    def test_an_untranslated_language_shows_the_source(self):
        [section] = self.questionnaire.translated('en').sections.all()

        self.assertEqual(section.title, 'Your growth')

    def test_the_original_stays_untouched(self):
        self.questionnaire.translated('de')

        [section] = self.questionnaire.sections.all()
        rating, likert = section.questions.all()
        self.assertEqual((self.questionnaire.name, section.title), ('Skills', 'Your growth'))
        self.assertEqual(rating.labels, {'1': 'Poor', '5': 'Excellent'})
        self.assertEqual([option.label for option in likert.options.all()], ['Agree', 'Disagree'])

    def test_a_copy_cannot_be_saved(self):
        questionnaire = self.questionnaire.translated('de')
        [section] = questionnaire.sections.all()

        with self.assertRaises(ValueError):
            questionnaire.save()

        with self.assertRaises(ValueError):
            section.save()

        self.questionnaire.refresh_from_db()
        self.assertEqual(self.questionnaire.name, 'Skills')

    def test_a_clone_keeps_the_source_language_and_the_translations(self):
        self.questionnaire.source_language = 'de-informal'
        self.questionnaire.save()
        other_organization = Organization.objects.create(name='Other', email='org@other.example')

        clone = clone_questionnaire_for_organization(self.questionnaire, other_organization)

        translated = clone.translated('de')
        [section] = translated.sections.all()
        rating, likert = section.questions.all()
        [action_item] = rating.action_items
        self.assertEqual(clone.source_language, 'de-informal')
        self.assertEqual((translated.name, section.title, rating.question_text), (
            'Fähigkeiten', 'Ihr Wachstum', 'Teilt Wissen'))
        self.assertEqual(action_item['text'], 'Wöchentlich zu zweit arbeiten')
        self.assertEqual([option.label for option in likert.options.all()], ['Stimme zu', 'Disagree'])
        self.assertEqual(QuestionTranslation.objects.filter(question__section__questionnaire=clone).count(), 1)


class TranslatedFormTest(TranslatedQuestionnaireTestCase):

    def setUp(self):
        super().setUp()
        self.token = ReviewerToken.objects.create(cycle=self.cycle, category='peer', language='de')

    def test_the_form_is_in_the_reviewers_language(self):
        page = self.client.get(reverse('reviews:feedback_form', args=[self.token.token]))

        for text in ['Ihr Wachstum', 'Teilt Wissen', 'Schwach', 'Excellent', 'Listens well', 'Stimme zu', 'Disagree']:
            self.assertContains(page, text)

        self.assertNotContains(page, 'Shares knowledge')

    def test_the_form_puts_the_first_name_into_the_translated_question(self):
        self.rating.translations.update(question_text='Teilt {name} Wissen?')

        page = self.client.get(reverse('reviews:feedback_form', args=[self.token.token]))

        self.assertContains(page, 'Teilt Dana Wissen?')

    def test_errors_quote_the_question_in_the_reviewers_language(self):
        response = self.client.post(reverse('reviews:submit_feedback', args=[self.token.token]))

        errors = ' '.join(response.json()['errors'])
        self.assertIn('Teilt Wissen', errors)
        self.assertNotIn('Shares knowledge', errors)

    def test_invitations_name_the_questionnaire_in_the_reviewers_language(self):
        self.token.reviewer_email = 'reviewer@acme.example'
        self.token.save()

        queue_invitations(self.cycle.tokens.all())
        send_queued_emails()

        [invitation] = mail.outbox
        self.assertIn('Fähigkeiten', invitation.body)
        self.assertNotIn('Skills', invitation.body)


class TranslatedPreviewTest(TranslatedQuestionnaireTestCase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def preview(self, **params):
        return self.client.get(reverse('questionnaire_preview', args=[self.questionnaire.uuid]), params)

    def test_the_preview_shows_the_source_language(self):
        page = self.preview()

        self.assertContains(page, 'Shares knowledge')
        self.assertNotContains(page, 'Teilt Wissen')

    def test_the_preview_shows_a_translation(self):
        page = self.preview(lang='de')

        self.assertContains(page, 'Teilt Wissen')
        self.assertContains(page, 'Stimme zu')
        self.assertContains(page, 'aria-current="page">Deutsch (Sie)')

    def test_an_unknown_language_shows_the_source_language(self):
        self.assertContains(self.preview(lang='xx'), 'Shares knowledge')


class TranslatedAPITest(TranslatedQuestionnaireTestCase):

    def setUp(self):
        super().setUp()
        token = APIToken.objects.create(organization=self.organization, created_by=self.admin, name='T')
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token.token}')

    def get_question_texts(self, url, **headers):
        [section] = self.api.get(url, **headers).json()['sections']

        return [question['question_text'] for question in section['questions']]

    def test_lang_picks_the_language(self):
        data = self.api.get(f'/api/v1/questionnaires/{self.questionnaire.uuid}/?lang=de').json()
        [section] = data['sections']
        rating, likert = section['questions']

        self.assertEqual((data['name'], data['source_language']), ('Fähigkeiten', 'en'))
        self.assertEqual(section['title'], 'Ihr Wachstum')
        self.assertEqual(rating['question_text'], 'Teilt Wissen')
        self.assertEqual(rating['labels'], {'1': 'Schwach', '5': 'Excellent'})
        self.assertEqual([option['label'] for option in likert['options']], ['Stimme zu', 'Disagree'])

    def test_without_lang_the_browser_language_counts(self):
        url = f'/api/v1/questionnaires/{self.questionnaire.uuid}/'

        texts = self.get_question_texts(url, HTTP_ACCEPT_LANGUAGE='de')

        self.assertEqual(texts, ['Teilt Wissen', 'Listens well'])

    def test_without_lang_and_browser_language_the_organizations_language_counts(self):
        self.organization.default_language = 'de'
        self.organization.save()
        url = f'/api/v1/questionnaires/{self.questionnaire.uuid}/'

        texts = self.get_question_texts(url)

        self.assertEqual(texts, ['Teilt Wissen', 'Listens well'])

    def test_the_list_and_the_cycle_questionnaire_are_translated(self):
        questionnaires = self.api.get('/api/v1/questionnaires/?lang=de').json()['results']
        texts = self.get_question_texts(f'/api/v1/cycles/{self.cycle.uuid}/questionnaire/?lang=de')

        self.assertIn('Fähigkeiten', [questionnaire['name'] for questionnaire in questionnaires])
        self.assertEqual(texts, ['Teilt Wissen', 'Listens well'])

    def test_the_questionnaire_of_a_cycle_has_the_first_name(self):
        self.rating.translations.update(question_text='Teilt {name} Wissen?')

        texts = self.get_question_texts(f'/api/v1/cycles/{self.cycle.uuid}/questionnaire/?lang=de')

        self.assertEqual(texts, ['Teilt Dana Wissen?', 'Listens well'])

    def test_cycles_keep_the_source_name(self):
        cycle = self.api.get(f'/api/v1/cycles/{self.cycle.uuid}/?lang=de').json()

        self.assertEqual(cycle['questionnaire_detail']['name'], 'Skills')


class TranslationStateTest(TranslatedQuestionnaireTestCase):

    def get_questionnaire(self):
        """The questionnaire as a request loads it, without the parts an earlier call prefetched."""

        return Questionnaire.objects.get(pk=self.questionnaire.pk)

    def get_texts(self, language='de'):
        return {(text.part, text.key): text for text in get_text_translations(self.get_questionnaire(), language)}

    def get_text(self, part, key, language='de'):
        return self.get_texts(language)[part, key]

    def save(self, language='de', confirm=False, **changes):
        """Save the current translations into language, all confirmed as up to date if asked, with changes applied."""

        texts = get_text_translations(self.get_questionnaire(), language)
        data = {text.field_name: text.text for text in texts}

        if confirm:
            data.update({f'current-{text.field_name}': 'on' for text in texts})

        data.update(changes)

        return save_text_translations(self.get_questionnaire(), language, data)

    def test_texts_without_translation_are_missing(self):
        self.assertTrue(self.get_text(self.likert, 'question_text').missing)
        self.assertFalse(self.get_text(self.rating, 'question_text').missing)

    def test_saving_stores_the_texts_with_the_checksums_of_their_source(self):
        field_name = self.get_text(self.likert, 'question_text').field_name

        self.save(**{field_name: 'Hört gut zu'})

        translation = self.likert.translations.get(language='de')
        self.assertEqual(translation.question_text, 'Hört gut zu')
        self.assertEqual(translation.source_checksums, {'question_text': get_checksum('Listens well')})
        self.assertFalse(self.get_text(self.likert, 'question_text').outdated)

    def test_a_changed_source_text_shows_its_translation_as_outdated(self):
        self.save(confirm=True)
        self.rating.question_text = 'Shares what they know'
        self.rating.save()

        self.assertTrue(self.get_text(self.rating, 'question_text').outdated)
        self.assertFalse(self.get_text(self.rating, 'labels.1').outdated)

    def test_an_outdated_text_stays_outdated_until_confirmed(self):
        self.save(confirm=True)
        self.rating.question_text = 'Shares what they know'
        self.rating.save()
        field_name = self.get_text(self.rating, 'question_text').field_name

        self.save()
        self.assertTrue(self.get_text(self.rating, 'question_text').outdated)

        self.save(**{f'current-{field_name}': 'on'})
        self.assertFalse(self.get_text(self.rating, 'question_text').outdated)

    def test_an_empty_text_removes_its_translation(self):
        self.save(**{self.get_text(self.rating, 'question_text').field_name: ''})

        translation = self.rating.translations.get(language='de')
        self.assertEqual(translation.question_text, '')
        self.assertEqual(translation.labels, {'1': 'Schwach'})

    def test_a_translation_without_texts_is_deleted(self):
        texts = get_text_translations(self.get_questionnaire(), 'de')

        self.save(**{text.field_name: '' for text in texts if text.part == self.rating})

        self.assertFalse(self.rating.translations.filter(language='de').exists())

    def test_saving_drops_texts_the_source_no_longer_has(self):
        self.save()

        self.assertNotIn('9', self.rating.translations.get(language='de').labels)

    def test_a_too_long_text_saves_nothing(self):
        errors = self.save(**{
            self.get_text(self.questionnaire, 'name').field_name: 'x' * 300,
            self.get_text(self.likert, 'question_text').field_name: 'Hört gut zu',
        })

        self.assertEqual(len(errors), 1)
        self.assertFalse(self.likert.translations.exists())

    def test_a_variant_shows_the_texts_of_its_base_language(self):
        question_text = self.get_text(self.rating, 'question_text', 'de-informal')
        title = self.get_text(self.section, 'title', 'de-informal')

        self.assertEqual((question_text.text, question_text.fallback), ('', 'Teilt Wissen'))
        self.assertFalse(question_text.missing)
        self.assertEqual((title.text, title.fallback), ('Dein Wachstum', 'Ihr Wachstum'))

    def test_a_variant_of_the_source_language_misses_nothing(self):
        self.questionnaire.source_language = 'de'
        self.questionnaire.save()

        self.assertFalse(any(text.missing for text in self.get_texts('de-informal').values()))
        self.assertTrue(self.get_text(self.likert, 'question_text', 'en').missing)


class TranslationEditorTest(TranslatedQuestionnaireTestCase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def translate_url(self, language='de', questionnaire=None):
        questionnaire = questionnaire or self.questionnaire

        return reverse('questionnaire_translate', args=[questionnaire.uuid, language])

    def edit(self, **data):
        return self.client.post(reverse('questionnaire_edit', args=[self.questionnaire.uuid]), data)

    def test_the_translation_page_shows_source_and_translation_side_by_side(self):
        page = self.client.get(self.translate_url())

        self.assertContains(page, 'Shares knowledge')
        self.assertContains(page, '>Teilt Wissen</textarea>')
        self.assertContains(page, 'value="Ihr Wachstum"')
        self.assertContains(page, 'Missing')

    def test_the_translation_page_explains_the_name_placeholder(self):
        self.likert.question_text = 'Does {name} listen?'
        self.likert.save()

        page = self.client.get(self.translate_url())

        self.assertContains(page, 'stands for the first name of the person reviewed', count=1)

    def test_the_translation_page_saves(self):
        field_name = f'question-{self.likert.id}-question_text'

        response = self.client.post(self.translate_url(), {field_name: 'Hört gut zu'})

        self.assertRedirects(response, self.translate_url())
        self.assertEqual(self.likert.translations.get(language='de').question_text, 'Hört gut zu')

    def test_only_other_languages_of_the_own_organization_can_be_translated(self):
        other = Questionnaire.objects.create(name='Other', organization=Organization.objects.create(
            name='Other', email='org@other.example'))

        self.assertEqual(self.client.get(self.translate_url('en')).status_code, 404)
        self.assertEqual(self.client.get(self.translate_url('xx')).status_code, 404)
        self.assertEqual(self.client.get(self.translate_url(questionnaire=other)).status_code, 404)

    def test_members_cannot_translate(self):
        member = User.objects.create_user('member', 'member@acme.example', 'pw')
        UserProfile.objects.create(user=member, organization=self.organization)
        self.client.force_login(member)

        self.client.post(self.translate_url(), {f'question-{self.likert.id}-question_text': 'Hört gut zu'})

        self.assertFalse(self.likert.translations.exists())

    def test_the_editor_and_the_list_show_how_far_the_translations_are(self):
        editor = self.client.get(reverse('questionnaire_edit', args=[self.questionnaire.uuid]))
        listing = self.client.get(reverse('questionnaire_list'))

        self.assertContains(editor, self.translate_url())
        self.assertContains(editor, 'texts missing')
        self.assertContains(listing, 'Deutsch (Sie):')

    def test_the_source_language_can_change_to_a_language_without_translation(self):
        self.edit(action='update_info', name='Skills', source_language='de-informal')
        self.questionnaire.refresh_from_db()
        self.assertEqual(self.questionnaire.source_language, 'en')

        QuestionSectionTranslation.objects.filter(language='de-informal').delete()
        self.edit(action='update_info', name='Skills', source_language='de-informal')
        self.questionnaire.refresh_from_db()
        self.assertEqual(self.questionnaire.source_language, 'de-informal')

    def test_a_new_questionnaire_takes_the_language_picked(self):
        self.client.post(reverse('questionnaire_create'), {'name': 'Fragen', 'source_language': 'de'})

        self.assertEqual(Questionnaire.objects.get(name='Fragen').source_language, 'de')

    def test_new_questions_get_the_default_labels_in_the_source_language(self):
        self.questionnaire.source_language = 'de'
        self.questionnaire.save()

        self.edit(action='add_question', section_id=self.section.id, question_type='likert', question_text='Hilft')
        self.edit(action='add_question', section_id=self.section.id, question_type='rating', question_text='Plant')

        with translation.override('de'):
            scale = [f'{label}' for label in DEFAULT_LIKERT_SCALE]

        likert = Question.objects.get(question_text='Hilft')
        rating = Question.objects.get(question_text='Plant')
        self.assertEqual([option.label for option in likert.options.all()], scale)
        self.assertEqual(rating.labels, {f'{value}': label for value, label in enumerate(scale, 1)})


class TranslationExportTest(TranslatedQuestionnaireTestCase):

    def export(self):
        """The questionnaire as the export file holds it."""

        data = json.loads(json.dumps(export_organization_data(self.organization)))
        [questionnaire] = [
            questionnaire for questionnaire in data['questionnaires'] if questionnaire['name'] == 'Skills'
        ]

        return questionnaire

    def import_into_other_organization(self, questionnaire_data):
        organization = Organization.objects.create(name='Other', email='org@other.example')
        result = import_questionnaires(organization, [questionnaire_data])

        return result['questionnaire_map']['Skills']

    def test_the_export_holds_the_source_language_translations_and_action_items(self):
        questionnaire = self.export()
        [section] = questionnaire['sections']
        rating, likert = section['questions']
        [action_item] = rating['action_items']
        agree, disagree = likert['options']

        self.assertEqual(questionnaire['source_language'], 'en')
        self.assertEqual(questionnaire['translations']['de']['name'], 'Fähigkeiten')
        self.assertEqual(section['translations']['de-informal']['title'], 'Dein Wachstum')
        self.assertEqual(action_item['key'], 'pairing')
        self.assertEqual(rating['translations']['de']['action_items'], {'pairing': 'Wöchentlich zu zweit arbeiten'})
        self.assertEqual(agree['translations']['de']['label'], 'Stimme zu')

    def test_an_import_restores_the_translations(self):
        questionnaire = self.import_into_other_organization(self.export()).translated('de')
        [section] = questionnaire.sections.all()
        rating, likert = section.questions.all()
        [action_item] = rating.action_items

        self.assertEqual((questionnaire.name, section.title, rating.question_text), (
            'Fähigkeiten', 'Ihr Wachstum', 'Teilt Wissen'))
        self.assertEqual(action_item['text'], 'Wöchentlich zu zweit arbeiten')
        self.assertEqual([option.label for option in likert.options.all()], ['Stimme zu', 'Disagree'])

    def test_an_import_leaves_out_unknown_languages_the_source_language_and_wrong_types(self):
        questionnaire_data = self.export()
        questionnaire_data['translations'] = {
            'xx': {'name': 'Unbekannt'},
            'en': {'name': 'Source'},
            'de': {'name': 5, 'description': 'Beschreibung', 'source_checksums': ['wrong']},
        }

        questionnaire = self.import_into_other_organization(questionnaire_data)

        [translation] = questionnaire.translations.all()
        self.assertEqual((translation.language, translation.name, translation.description), ('de', '', 'Beschreibung'))
        self.assertEqual(translation.source_checksums, {})

    def test_an_export_from_before_translations_imports_in_the_default_language(self):
        questionnaire_data = self.export()

        for key in ['source_language', 'translations']:
            questionnaire_data.pop(key)

        for section in questionnaire_data['sections']:
            section.pop('translations')

            for question in section['questions']:
                question.pop('translations')
                question.pop('action_items')

        questionnaire = self.import_into_other_organization(questionnaire_data)

        self.assertEqual(questionnaire.source_language, 'en')
        self.assertFalse(questionnaire.translations.exists())
        [section] = questionnaire.sections.all()
        self.assertEqual([question.action_items for question in section.questions.all()], [[], []])

