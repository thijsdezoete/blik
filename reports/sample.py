"""A sample report PDF for the landing pages, built fresh from the current code and rolled back.

Nothing is stored: the demo organization, cycle and answers live inside one transaction that is
rolled back after the PDF is rendered. `manage.py export_sample_pdf` writes it when the landing
container starts, so every deploy ships a sample with the latest report layout.
"""
import random

from django.db import transaction

from accounts.models import Reviewee
from core.models import Organization
from questionnaires.models import Question, Questionnaire
from reports.pdf import render_report_pdf
from reports.services import generate_report
from reviews.models import ReviewCycle, ReviewerToken, Response

SAMPLE_QUESTIONNAIRE = 'Manager 360 Review'   # shipped template, installed by `manage.py upgrade`
SAMPLE_NAME = 'Anna de Vries'
# Every rater answers around 3.6 on a 1–5 scale; self a little higher, so the report shows a gap.
RATERS = {'self': [0.6], 'peer': [0, 0.2, -0.3, 0.1], 'manager': [-0.2], 'direct_report': [0.3, 0]}
COMMENTS = ['Clear in meetings.', 'Could delegate more.', 'Very supportive when things go wrong.']


class _Rollback(Exception):
    pass


def _answer(question, rng, bias):
    if question.question_type in ('rating', 'likert', 'scale'):
        lo, hi = question.config.get('min', 1), question.config.get('max', 5)
        return max(lo, min(hi, round(rng.gauss(3.6 + bias, 0.7))))
    if question.question_type == 'text':
        return rng.choice(COMMENTS)
    return None


def build_sample_pdf(language):
    """PDF bytes of the sample report, or None when the shipped questionnaire is not installed."""
    questionnaire = Questionnaire.objects.filter(name=SAMPLE_QUESTIONNAIRE, organization__isnull=True).first()
    if questionnaire is None:
        return None
    questions = list(Question.objects.filter(section__questionnaire=questionnaire).order_by('section__order', 'order'))

    pdf = None
    try:
        with transaction.atomic():
            organization = Organization.objects.create(name='Blik', email='sample@blik.invalid')
            reviewee = Reviewee.objects.create(organization=organization, name=SAMPLE_NAME,
                                               email='anna@blik.invalid', department='Operations')
            cycle = ReviewCycle.objects.create(reviewee=reviewee, questionnaire=questionnaire, status='completed')
            for category, biases in RATERS.items():
                for i, bias in enumerate(biases):
                    rng = random.Random(f'{category}{i}')
                    token = ReviewerToken.objects.create(cycle=cycle, category=category)
                    for question in questions:
                        value = _answer(question, rng, bias)
                        if value is not None:
                            Response.objects.create(cycle=cycle, question=question, token=token,
                                                    category=category, answer_data={'value': value})
            report = generate_report(cycle, notify=False)
            pdf = render_report_pdf(report, language)
            raise _Rollback
    except _Rollback:
        pass
    return pdf

