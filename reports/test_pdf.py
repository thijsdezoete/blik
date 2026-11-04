import os
import re
import tempfile
from datetime import datetime, timezone as dt_timezone
from unittest import mock

from django.test import TestCase, override_settings

from accounts.models import Reviewee
from core.models import Organization
from questionnaires.models import AnswerOption, Question, Questionnaire, QuestionSection
from reviews.models import ReviewCycle, ReviewerToken, Response

from .models import Report
from .pdf import drop_report_pdf, pdf_filename, render_report_pdf, report_pdf_document, report_pdf_html, \
    reviewee_language, store_report_pdf
from .services import generate_report

LABELS = {'1': 'Waits for instructions', '2': 'Needs help', '3': 'Works alone', '4': 'Leads', '5': 'Self-driven'}
MAPPED = {'min': 1, 'max': 5, 'dreyfus_mapping': {'skill': 1.0, 'agency': 1.0}}


class ReportPdfTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='Acme', email='org@acme.example', min_responses_for_anonymity=3,
        )
        self.questionnaire = Questionnaire.objects.create(name='Skills', organization=self.organization)

    def add_questions(self, config):
        craft = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Craft', order=0)
        team = QuestionSection.objects.create(questionnaire=self.questionnaire, title='Teamwork', order=1)
        self.craft = Question.objects.create(
            section=craft, question_text='Solves problems', question_type='rating', config=config, labels=LABELS,
        )
        self.team = Question.objects.create(
            section=team, question_text='Helps others', question_type='rating', config=config,
        )
        self.traits = Question.objects.create(
            section=team, question_text='Traits', question_type='multiple_choice', config={}, order=1,
        )
        self.listens = AnswerOption.objects.create(question=self.traits, order=0, label='Listens well')
        self.credit = AnswerOption.objects.create(question=self.traits, order=1, label='Gives credit')
        self.comment = Question.objects.create(
            section=team, question_text='Anything else?', question_type='text', config={}, order=2,
        )

    def cycle(self, name, answers):
        """A completed cycle; answers maps a category to one answers dict per reviewer."""
        reviewee = Reviewee.objects.create(
            name=name, email=f'r{Reviewee.objects.count()}@acme.example', organization=self.organization,
        )
        cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=self.questionnaire, status='completed')
        for category, reviewers in answers.items():
            for values in reviewers:
                token = ReviewerToken.objects.create(cycle=cycle, category=category)
                for question, value in values.items():
                    Response.objects.create(
                        cycle=cycle, question=question, token=token, category=category, answer_data={'value': value},
                    )
        return cycle

    def full_report(self, config=MAPPED, peers=3):
        self.add_questions(config)
        reviewers = {
            'self': [{self.craft: 3, self.team: 4, self.comment: 'I try.'}],
            'peer': [
                {self.craft: 5, self.team: 4, self.traits: [self.listens.id, self.credit.id], self.comment: 'Kind.'},
                {self.craft: 5, self.team: 5, self.traits: [self.credit.id], self.comment: 'Sharp.'},
                {self.craft: 4, self.team: 4, self.traits: [self.credit.id], self.comment: 'Calm.'},
            ][:peers],
            'manager': [{self.craft: 5, self.team: 5, self.comment: 'Reliable.'}],
        }
        return generate_report(self.cycle('Anna de Vries', reviewers))

    def test_render_report_pdf_returns_pdf_bytes(self):
        report = self.full_report()

        pdf = render_report_pdf(report, 'en')

        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreaterEqual(len(report_pdf_document(report, 'en').pages), 3)

    def test_render_without_dreyfus_mapping_builds(self):
        report = self.full_report(config={'min': 1, 'max': 5})
        self.assertIsNone(report.report_data['insights'].get('skill_profile'))

        self.assertTrue(render_report_pdf(report, 'en').startswith(b'%PDF'))

    def test_render_with_hidden_peer_group_leaves_peers_out(self):
        report = self.full_report(peers=2)

        html = report_pdf_html(report, 'en')

        self.assertIn('Insufficient responses (minimum 3 required)', html)
        self.assertNotIn('Kind.', html)
        self.assertTrue(render_report_pdf(report, 'en').startswith(b'%PDF'))

    def test_render_without_visible_others_builds(self):
        self.add_questions(MAPPED)
        report = generate_report(self.cycle('Anna de Vries', {
            'self': [{self.craft: 3}], 'peer': [{self.craft: 5}, {self.craft: 4}],
        }))

        self.assertTrue(render_report_pdf(report, 'en').startswith(b'%PDF'))

    def test_pdf_contains_web_report_details(self):
        self.add_questions(MAPPED)
        # Six earlier reviewees with lower scores make a peer benchmark
        for i in range(6):
            self.cycle(f'Other {i}', {'peer': [{self.craft: 2, self.team: 2}] * 3})
            generate_report(ReviewCycle.objects.get(reviewee__name=f'Other {i}'))
        report = generate_report(self.cycle('Anna de Vries', {
            'self': [{self.craft: 3, self.team: 4}],
            'peer': [
                {self.craft: 5, self.team: 4, self.traits: [self.listens.id, self.credit.id]},
                {self.craft: 5, self.team: 5, self.traits: [self.credit.id]},
                {self.craft: 4, self.team: 4, self.traits: [self.credit.id]},
            ],
            'manager': [{self.craft: 5, self.team: 5}],
        }))

        html = report_pdf_html(report, 'en')

        self.assertIn('67%', html)  # two of three peers rated 5
        self.assertIn('Strong consensus: 100% positive (3 of 3 respondents)', html)  # peers on Teamwork
        self.assertNotIn('(1 of 1 respondents)', html)  # a group of one has no consensus
        self.assertRegex(html, r'Scale:[^<]*1 = Waits for instructions[^<]*5 = Self-driven')
        self.assertIn('3 responses', html)
        strengths = report.report_data['insights']['strengths']
        self.assertTrue(strengths)
        for strength in strengths:
            self.assertIn(strength['area'], html)
        self.assertIn('Gives credit', html)
        self.assertRegex(html, r'higher than \d+% of peers')

    def test_store_and_drop_report_pdf(self):
        self.add_questions(MAPPED)
        report = generate_report(self.cycle('Anna de Vries', {'manager': [{self.craft: 4}]}))

        with tempfile.TemporaryDirectory() as tmp, override_settings(PRIVATE_MEDIA_ROOT=tmp), \
                mock.patch('reports.pdf.render_report_pdf', side_effect=[b'%PDF first', b'%PDF second']):
            store_report_pdf(report)
            first = report.pdf_file.path
            store_report_pdf(report)
            report.refresh_from_db()

            self.assertNotEqual(first, report.pdf_file.path)
            self.assertFalse(os.path.exists(first))
            with report.pdf_file.open('rb') as stored:
                self.assertEqual(stored.read(), b'%PDF second')
            self.assertIsNotNone(report.pdf_generated_at)
            self.assertTrue(report.has_valid_pdf())

            path = report.pdf_file.path
            drop_report_pdf(report)
            report.refresh_from_db()

            self.assertFalse(os.path.exists(path))
            self.assertFalse(report.pdf_file)
            self.assertIsNone(report.pdf_generated_at)

    def report_named(self, name):
        self.add_questions(MAPPED)
        report = generate_report(self.cycle(name, {'manager': [{self.craft: 4}]}))
        Report.objects.filter(pk=report.pk).update(generated_at=datetime(2026, 11, 3, 12, tzinfo=dt_timezone.utc))
        report.refresh_from_db()
        return report

    def test_pdf_filename(self):
        self.assertEqual(pdf_filename(self.report_named('Anna de Vries')), 'anna-de-vries-360-feedback-2026-11-03.pdf')

    def test_pdf_filename_non_ascii_and_empty_slug(self):
        self.assertEqual(pdf_filename(self.report_named('Zoë Ångström')), 'zoe-angstrom-360-feedback-2026-11-03.pdf')

        report = generate_report(self.cycle('李雷', {'manager': [{self.craft: 4}]}))
        Report.objects.filter(pk=report.pk).update(generated_at=datetime(2026, 11, 3, 12, tzinfo=dt_timezone.utc))
        report.refresh_from_db()
        self.assertEqual(
            pdf_filename(report), f'report-{str(report.cycle.uuid)[:8]}-360-feedback-2026-11-03.pdf',
        )
        self.assertTrue(re.fullmatch(r'[a-z0-9-]+\.pdf', pdf_filename(report)))

    def test_reviewee_language(self):
        report = self.report_named('Anna de Vries')
        report.cycle.reviewee.language = 'de'

        self.assertEqual(reviewee_language(report), 'de')
