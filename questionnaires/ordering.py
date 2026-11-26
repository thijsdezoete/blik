"""The order of the sections of a questionnaire and of the questions in them, as the editor drags them around."""

from django.db import transaction
from django.db.models import F

from .models import Question, QuestionSection


def save_layout(questionnaire, layout):
    """
    Put the sections and questions of questionnaire in the order of layout: [{"section": id, "questions": [id, ...]}].
    A question can move to another section. Raises ValueError unless layout holds every section and question once, by
    ids that are whole numbers.
    """

    sections = {section.id: section for section in questionnaire.sections.all()}
    questions = {question.id: question for question in Question.objects.filter(section__questionnaire=questionnaire)}
    section_ids = [entry['section'] for entry in layout]
    question_ids = [question_id for entry in layout for question_id in entry['questions']]

    # 1.0 or True would match the id 1 below, and end up in the editor's answer as another id
    if not all(type(item_id) is int for item_id in section_ids + question_ids):
        raise ValueError('The ids of the layout must be whole numbers')

    if sorted(section_ids) != sorted(sections) or sorted(question_ids) != sorted(questions):
        raise ValueError('The layout must hold every section and question of the questionnaire once')

    for order, entry in enumerate(layout):
        sections[entry['section']].order = order

        for question_order, question_id in enumerate(entry['questions']):
            question = questions[question_id]
            question.section_id = entry['section']
            question.order = question_order

    with transaction.atomic():
        # Out of the way first: the orders are unique per questionnaire and per section, and ids never repeat
        QuestionSection.objects.filter(id__in=sections).update(order=F('id') * -1)
        Question.objects.filter(id__in=questions).update(order=F('id') * -1)
        QuestionSection.objects.bulk_update(sections.values(), ['order'])
        Question.objects.bulk_update(questions.values(), ['section', 'order'])
