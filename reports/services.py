from django.db.models import Avg, Count
from collections import defaultdict
from .models import Report
from reviews.models import Response, ReviewCycle


MINIMUM_RESPONSES_THRESHOLD = 3


def generate_report(cycle):
    """Generate aggregated report for a review cycle"""

    questionnaire = cycle.questionnaire

    # Get all responses for this cycle
    responses = Response.objects.filter(cycle=cycle).select_related(
        'question', 'question__section'
    )

    # Group responses by section and question
    data_by_section = defaultdict(lambda: {
        'title': '',
        'questions': defaultdict(lambda: {
            'question_text': '',
            'question_type': '',
            'by_category': defaultdict(lambda: {
                'responses': [],
                'count': 0,
                'avg': None
            })
        })
    })

    for response in responses:
        section = response.question.section
        question = response.question

        # Set section title
        data_by_section[section.id]['title'] = section.title

        # Set question details
        question_data = data_by_section[section.id]['questions'][question.id]
        question_data['question_text'] = question.question_text
        question_data['question_type'] = question.question_type

        # Add response to category
        category_data = question_data['by_category'][response.category]
        category_data['responses'].append(response.answer_data.get('value'))
        category_data['count'] += 1

    # Calculate averages and apply anonymity threshold
    report_data = {'by_section': {}}

    for section_id, section_data in data_by_section.items():
        report_section = {
            'title': section_data['title'],
            'questions': {}
        }

        for question_id, question_data in section_data['questions'].items():
            report_question = {
                'question_text': question_data['question_text'],
                'question_type': question_data['question_type'],
                'by_category': {}
            }

            for category, category_data in question_data['by_category'].items():
                count = category_data['count']

                # Apply anonymity threshold (except for self-assessment)
                if category == 'self' or count >= MINIMUM_RESPONSES_THRESHOLD:
                    result = {
                        'count': count,
                        'responses': category_data['responses']
                    }

                    # Calculate average for rating questions
                    if question_data['question_type'] == 'rating':
                        numeric_responses = [r for r in category_data['responses'] if isinstance(r, (int, float))]
                        if numeric_responses:
                            result['avg'] = round(sum(numeric_responses) / len(numeric_responses), 2)

                    report_question['by_category'][category] = result
                else:
                    # Insufficient responses - hide for anonymity
                    report_question['by_category'][category] = {
                        'count': count,
                        'insufficient': True,
                        'message': f'Insufficient responses (minimum {MINIMUM_RESPONSES_THRESHOLD} required)'
                    }

            report_section['questions'][str(question_id)] = report_question

        report_data['by_section'][str(section_id)] = report_section

    # Create or update report
    report, created = Report.objects.update_or_create(
        cycle=cycle,
        defaults={
            'report_data': report_data,
            'available': True
        }
    )

    return report


def get_report_summary(report):
    """Get summary statistics from a report"""
    summary = {
        'total_responses': 0,
        'by_category': {},
    }

    # Count unique responses per category
    category_counts = defaultdict(int)

    for section_data in report.report_data.get('by_section', {}).values():
        for question_data in section_data.get('questions', {}).values():
            for category, cat_data in question_data.get('by_category', {}).items():
                if not cat_data.get('insufficient'):
                    count = cat_data.get('count', 0)
                    if count > 0:
                        category_counts[category] = max(category_counts[category], count)

    # Convert to regular dict and calculate total
    summary['by_category'] = dict(category_counts)
    summary['total_responses'] = sum(category_counts.values())

    return summary
