"""
Factory definitions for questionnaire models
"""
import factory
from factory.django import DjangoModelFactory
from .models import Questionnaire, QuestionSection, Question
from core.factories import OrganizationFactory


class QuestionnaireFactory(DjangoModelFactory):
    """Factory for creating questionnaires"""

    class Meta:
        model = Questionnaire

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'Questionnaire {n}')
    description = factory.Faker('sentence')
    is_default = False
    is_active = True


class QuestionSectionFactory(DjangoModelFactory):
    """Factory for creating question sections"""

    class Meta:
        model = QuestionSection

    questionnaire = factory.SubFactory(QuestionnaireFactory)
    title = factory.Faker('sentence', nb_words=3)
    description = factory.Faker('sentence')
    order = factory.Sequence(lambda n: n)


class QuestionFactory(DjangoModelFactory):
    """Factory for creating questions"""

    class Meta:
        model = Question

    section = factory.SubFactory(QuestionSectionFactory)
    question_text = factory.Faker('sentence', nb_words=8)
    question_type = 'rating'
    config = factory.LazyFunction(lambda: {
        'min': 1,
        'max': 5,
        'labels': {
            '1': 'Poor',
            '3': 'Average',
            '5': 'Excellent'
        }
    })
    required = True
    order = factory.Sequence(lambda n: n)


class RatingQuestionFactory(QuestionFactory):
    """Factory for rating questions"""

    question_type = 'rating'
    config = factory.LazyFunction(lambda: {
        'min': 1,
        'max': 5,
        'labels': {
            '1': 'Needs improvement',
            '3': 'Meets expectations',
            '5': 'Exceeds expectations'
        }
    })


class TextQuestionFactory(QuestionFactory):
    """Factory for text questions"""

    question_type = 'text'
    config = {}


class LikertQuestionFactory(QuestionFactory):
    """Factory for Likert scale questions"""

    question_type = 'likert'
    config = factory.LazyFunction(lambda: {
        'scale': [
            'Strongly Disagree',
            'Disagree',
            'Neutral',
            'Agree',
            'Strongly Agree'
        ]
    })
