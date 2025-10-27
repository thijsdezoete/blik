from django.db.models import Avg, Count
from collections import defaultdict
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from core.email import send_email
from .models import Report
from reviews.models import Response, ReviewCycle
from core.models import Organization
from statistics import mean, stdev


def _calculate_insights(report_data):
    """Generate actionable insights from report data"""
    insights = {
        'perception_gaps': [],
        'strengths': [],
        'development_areas': [],
        'skill_profile': None,
        'overall_sentiment': None
    }

    # Collect all rating averages by section and category
    section_averages = defaultdict(lambda: defaultdict(list))
    all_self_ratings = []
    all_peer_ratings = []
    all_manager_ratings = []

    for section_id, section_data in report_data.get('by_section', {}).items():
        section_title = section_data.get('title', '')

        for question_id, question_data in section_data.get('questions', {}).items():
            # Only process rating questions for numeric insights (likert is text-based)
            if question_data.get('question_type') != 'rating':
                continue

            for category, cat_data in question_data.get('by_category', {}).items():
                if cat_data.get('insufficient'):
                    continue

                avg = cat_data.get('avg')
                if avg is not None:
                    section_averages[section_title][category].append(avg)

                    if category == 'self':
                        all_self_ratings.append(avg)
                    elif category == 'peer':
                        all_peer_ratings.append(avg)
                    elif category == 'manager':
                        all_manager_ratings.append(avg)

    # Calculate section-level averages
    section_summary = {}
    for section_title, categories in section_averages.items():
        section_summary[section_title] = {}
        for category, ratings in categories.items():
            if ratings:
                section_summary[section_title][category] = round(mean(ratings), 2)

    # Identify perception gaps (self vs others)
    if all_self_ratings and (all_peer_ratings or all_manager_ratings):
        self_avg = mean(all_self_ratings)
        others_ratings = all_peer_ratings + all_manager_ratings
        others_avg = mean(others_ratings) if others_ratings else None

        if others_avg is not None:
            gap = self_avg - others_avg

            if gap < -0.5:
                insights['perception_gaps'].append({
                    'type': 'imposter_syndrome',
                    'severity': 'high' if gap < -1.0 else 'moderate',
                    'message': f'Self-assessment ({self_avg:.1f}) significantly lower than others\' perception ({others_avg:.1f})',
                    'interpretation': 'Strong performance but may undervalue own contributions'
                })
            elif gap > 0.5:
                insights['perception_gaps'].append({
                    'type': 'overconfidence',
                    'severity': 'high' if gap > 1.0 else 'moderate',
                    'message': f'Self-assessment ({self_avg:.1f}) higher than others\' perception ({others_avg:.1f})',
                    'interpretation': 'Opportunity to align self-perception with team feedback'
                })

    # Identify strengths (avg >= 4.0) and development areas (avg < 3.0)
    for section_title, categories in section_summary.items():
        # Use non-self categories for strengths/weaknesses
        relevant_scores = [v for k, v in categories.items() if k != 'self']
        if relevant_scores:
            avg_score = mean(relevant_scores)

            if avg_score >= 4.0:
                insights['strengths'].append({
                    'area': section_title,
                    'score': avg_score,
                    'level': 'exceptional' if avg_score >= 4.5 else 'strong'
                })
            elif avg_score < 3.0:
                insights['development_areas'].append({
                    'area': section_title,
                    'score': avg_score,
                    'priority': 'high' if avg_score < 2.5 else 'medium'
                })

    # Detect Dreyfus skill level from technical expertise section
    tech_section = section_summary.get('Technical Expertise & Skill Level', {})
    if tech_section:
        tech_scores = [v for v in tech_section.values() if v]
        if tech_scores:
            avg_tech = mean(tech_scores)

            if avg_tech >= 4.5:
                insights['skill_profile'] = {
                    'level': 'Expert',
                    'description': 'Works from intuition, creates new approaches, recognized authority'
                }
            elif avg_tech >= 3.5:
                insights['skill_profile'] = {
                    'level': 'Proficient',
                    'description': 'Sees big picture, recognizes patterns, works independently'
                }
            elif avg_tech >= 2.5:
                insights['skill_profile'] = {
                    'level': 'Competent',
                    'description': 'Plans deliberately, solves standard problems'
                }
            elif avg_tech >= 1.5:
                insights['skill_profile'] = {
                    'level': 'Advanced Beginner',
                    'description': 'Handles simple tasks independently'
                }
            else:
                insights['skill_profile'] = {
                    'level': 'Novice',
                    'description': 'Follows rules, needs detailed instructions'
                }

    # Overall sentiment
    all_ratings = all_self_ratings + all_peer_ratings + all_manager_ratings
    if all_ratings:
        overall_avg = mean(all_ratings)
        insights['overall_sentiment'] = {
            'score': round(overall_avg, 2),
            'rating': 'Outstanding' if overall_avg >= 4.5 else
                     'Excellent' if overall_avg >= 4.0 else
                     'Strong' if overall_avg >= 3.5 else
                     'Developing' if overall_avg >= 3.0 else
                     'Needs Support'
        }

    return insights, section_summary


def _calculate_chart_data(report_data, cycle):
    """
    Calculate weighted section averages and prepare chart-ready data

    Returns dict with chart data structure:
    {
        'section_scores': {section_title: {category: score}},
        'overall': {category: score}
    }
    """
    from questionnaires.models import Question

    chart_data = {
        'section_scores': {},
        'overall': {}
    }

    # Collect all category scores
    all_scores_by_category = defaultdict(list)

    for section_id, section_data in report_data.get('by_section', {}).items():
        section_title = section_data.get('title', '')
        section_scores = defaultdict(lambda: {'total': 0, 'weight_sum': 0})

        for question_id, question_data in section_data.get('questions', {}).items():
            # Get question to check chart config
            try:
                question = Question.objects.get(id=question_id)
                chart_weight = question.config.get('chart_weight', 1.0)
                exclude_from_charts = question.config.get('exclude_from_charts', False)

                # Skip if excluded
                if exclude_from_charts:
                    continue
            except Question.DoesNotExist:
                chart_weight = 1.0

            # Only process rating questions for charts
            if question_data.get('question_type') != 'rating':
                continue

            for category, cat_data in question_data.get('by_category', {}).items():
                if cat_data.get('insufficient'):
                    continue

                avg = cat_data.get('avg')
                if avg is not None:
                    section_scores[category]['total'] += avg * chart_weight
                    section_scores[category]['weight_sum'] += chart_weight

        # Calculate weighted averages for this section
        section_chart_data = {}
        for category, scores in section_scores.items():
            if scores['weight_sum'] > 0:
                weighted_avg = round(scores['total'] / scores['weight_sum'], 2)
                section_chart_data[category] = weighted_avg
                all_scores_by_category[category].append(weighted_avg)

        if section_chart_data:
            chart_data['section_scores'][section_title] = section_chart_data

    # Calculate overall scores
    for category, scores in all_scores_by_category.items():
        if scores:
            chart_data['overall'][category] = round(mean(scores), 2)

    # Calculate "others" average (non-self categories)
    for section_title, section_scores in chart_data['section_scores'].items():
        others_scores = [v for k, v in section_scores.items() if k != 'self']
        if others_scores:
            section_scores['others_avg'] = round(mean(others_scores), 2)

    others_overall = [v for k, v in chart_data['overall'].items() if k != 'self']
    if others_overall:
        chart_data['overall']['others_avg'] = round(mean(others_overall), 2)

    return chart_data


def generate_report(cycle):
    """Generate aggregated report for a review cycle"""

    questionnaire = cycle.questionnaire

    # Get organization's anonymity threshold
    organization = cycle.organization
    min_threshold = organization.min_responses_for_anonymity if organization else 3

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
                if category == 'self' or count >= min_threshold:
                    result = {
                        'count': count,
                        'responses': category_data['responses']
                    }

                    # Calculate average for rating and likert questions
                    if question_data['question_type'] == 'rating':
                        numeric_responses = [r for r in category_data['responses'] if isinstance(r, (int, float))]
                        if numeric_responses:
                            result['avg'] = round(sum(numeric_responses) / len(numeric_responses), 2)
                    elif question_data['question_type'] == 'likert':
                        # Convert likert text responses to numeric scores (1-indexed position in scale)
                        # Store both the text distribution and numeric average
                        from collections import Counter
                        text_responses = [r for r in category_data['responses'] if r]
                        if text_responses:
                            result['distribution'] = dict(Counter(text_responses))
                            # For numeric calculations, use position in scale (1-indexed)
                            # This allows averaging likert responses

                    report_question['by_category'][category] = result
                else:
                    # Insufficient responses - hide for anonymity
                    report_question['by_category'][category] = {
                        'count': count,
                        'insufficient': True,
                        'message': f'Insufficient responses (minimum {min_threshold} required)'
                    }

            report_section['questions'][str(question_id)] = report_question

        report_data['by_section'][str(section_id)] = report_section

    # Generate insights and analytics
    insights, section_summary = _calculate_insights(report_data)
    report_data['insights'] = insights
    report_data['section_summary'] = section_summary

    # Generate chart data
    chart_data = _calculate_chart_data(report_data, cycle)
    report_data['charts'] = chart_data

    # Create or update report
    report, created = Report.objects.update_or_create(
        cycle=cycle,
        defaults={
            'report_data': report_data,
            'available': True
        }
    )

    # Ensure access token is set
    if not report.access_token:
        import uuid
        report.access_token = uuid.uuid4()
        report.save()

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


def send_report_ready_notification(report, request=None):
    """
    Send email to reviewee when their report is ready

    Args:
        report: Report instance
        request: Optional request object for building absolute URLs

    Returns:
        dict: Statistics about email sent
    """
    stats = {
        'sent': 0,
        'errors': []
    }

    cycle = report.cycle
    reviewee = cycle.reviewee

    if not reviewee.email:
        stats['errors'].append(f"No email address for reviewee {reviewee.name}")
        return stats

    if not report.access_token:
        stats['errors'].append("Report does not have an access token")
        return stats

    # Build absolute URL
    if request:
        base_url = f"{request.scheme}://{request.get_host()}"
    else:
        base_url = settings.SITE_URL

    report_url = f"{base_url}{reverse('reports:reviewee_report', kwargs={'access_token': report.access_token})}"

    # Get response count
    summary = get_report_summary(report)
    response_count = summary.get('total_responses', 0)

    try:
        context = {
            'reviewee': reviewee,
            'cycle': cycle,
            'report_url': report_url,
            'response_count': response_count,
        }

        html_message = render_to_string('emails/report_ready.html', context)
        text_message = render_to_string('emails/report_ready.txt', context)

        send_email(
            subject=f'Your 360 Feedback Report is Ready!',
            message=text_message,
            recipient_list=[reviewee.email],
            html_message=html_message,
        )

        stats['sent'] += 1

    except Exception as e:
        stats['errors'].append(f"Failed to send report ready email: {str(e)}")

    return stats
