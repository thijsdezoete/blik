from django.db.models import Avg, Count
from collections import defaultdict
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from core.email import send_email
from .models import Report
from reviews.models import Response, ReviewCycle
from core.models import Organization
from statistics import mean, stdev, median
import copy


def _get_previous_cycle_report(cycle):
    """
    Find the most recent completed cycle for the same reviewee with the same questionnaire.
    Returns the Report object if found, None otherwise.
    """
    previous_cycle = ReviewCycle.objects.filter(
        reviewee=cycle.reviewee,
        questionnaire=cycle.questionnaire,
        status='completed',
        created_at__lt=cycle.created_at
    ).order_by('-created_at').first()

    if previous_cycle:
        try:
            return Report.objects.get(cycle=previous_cycle, available=True)
        except Report.DoesNotExist:
            return None
    return None


def _calculate_trend_indicator(current_score, previous_score):
    """
    Calculate trend indicator based on score change.
    Returns: {'direction': str, 'change': float, 'symbol': str}
    """
    if previous_score is None or current_score is None:
        return None

    change = current_score - previous_score

    # Define thresholds
    if change >= 0.3:
        return {'direction': 'up', 'change': change, 'symbol': '↑', 'label': 'Improved'}
    elif change >= 0.1:
        return {'direction': 'slight_up', 'change': change, 'symbol': '↗', 'label': 'Slightly improved'}
    elif change <= -0.3:
        return {'direction': 'down', 'change': change, 'symbol': '↓', 'label': 'Declined'}
    elif change <= -0.1:
        return {'direction': 'slight_down', 'change': change, 'symbol': '↘', 'label': 'Slightly declined'}
    else:
        return {'direction': 'stable', 'change': change, 'symbol': '→', 'label': 'Stable'}


def _calculate_peer_benchmarks(cycle, section_summary):
    """
    Calculate peer benchmarks by comparing to other reviewees in the same organization.
    Returns benchmark data with percentiles and distribution info.
    """
    organization = cycle.organization
    if not organization:
        return None

    # Get all completed cycles for the same questionnaire in the organization (excluding current cycle)
    peer_cycles = ReviewCycle.objects.filter(
        reviewee__organization=organization,
        questionnaire=cycle.questionnaire,
        status='completed'
    ).exclude(id=cycle.id)

    if peer_cycles.count() < 3:  # Need at least 3 peers for meaningful comparison
        return None

    benchmarks = {}

    # Collect peer scores for each section
    for section_name in section_summary.keys():
        peer_scores = []

        for peer_cycle in peer_cycles:
            try:
                peer_report = Report.objects.get(cycle=peer_cycle, available=True)
                peer_section = peer_report.report_data.get('section_summary', {}).get(section_name, {})

                # Get "others" average (excluding self)
                others_scores = [v for k, v in peer_section.items() if k != 'self']
                if others_scores:
                    peer_scores.append(mean(others_scores))
            except Report.DoesNotExist:
                continue

        if len(peer_scores) >= 3:
            # Calculate current reviewee's score
            current_section = section_summary.get(section_name, {})
            current_others_scores = [v for k, v in current_section.items() if k != 'self']

            if current_others_scores:
                current_score = mean(current_others_scores)
                peer_scores_sorted = sorted(peer_scores)

                # Calculate percentile
                below_count = sum(1 for s in peer_scores if s < current_score)
                percentile = round((below_count / len(peer_scores)) * 100)

                # Determine if percentile should be shown (only for good performance)
                peer_count = len(peer_scores)
                show_percentile = False

                if peer_count >= 16:
                    # Larger teams: show if top 33% (67th percentile+)
                    show_percentile = percentile >= 67
                elif peer_count >= 6:
                    # Medium teams: show if top 25% (75th percentile+)
                    show_percentile = percentile >= 75
                # Small teams (< 6): never show percentiles (not meaningful)

                benchmarks[section_name] = {
                    'current_score': round(current_score, 2),
                    'peer_median': round(median(peer_scores), 2),
                    'peer_mean': round(mean(peer_scores), 2),
                    'peer_min': round(min(peer_scores), 2),
                    'peer_max': round(max(peer_scores), 2),
                    'percentile': percentile,
                    'peer_count': peer_count,
                    'distribution': peer_scores_sorted,
                    'show_percentile': show_percentile  # Only show if performing well
                }

    return benchmarks if benchmarks else None


def apply_display_anonymization(report_data, min_threshold, exempt_categories=None):
    """
    Apply anonymization filtering to report data for display purposes.

    This function adds 'insufficient' flags to categories that don't meet
    the anonymization threshold, while preserving the underlying data.
    Charts and insights should use the raw data; only detailed report
    displays should use this filtered version.

    Args:
        report_data: The raw report data structure
        min_threshold: Minimum number of responses required for display
        exempt_categories: List of categories exempt from threshold (default: ['self', 'manager'])

    Returns:
        Copy of report_data with 'insufficient' flags added where applicable
    """
    if exempt_categories is None:
        exempt_categories = ['self', 'manager']

    # Deep copy to avoid modifying original data
    filtered_data = copy.deepcopy(report_data)

    # Walk through all questions and apply threshold
    for section_id, section_data in filtered_data.get('by_section', {}).items():
        for question_id, question_data in section_data.get('questions', {}).items():
            for category, cat_data in question_data.get('by_category', {}).items():
                count = cat_data.get('count', 0)

                # Check if category meets anonymization threshold
                if category not in exempt_categories and count < min_threshold:
                    # Mark as insufficient for display
                    cat_data['insufficient'] = True
                    cat_data['message'] = f'Insufficient responses (minimum {min_threshold} required)'
                    # Remove detailed responses and distributions for privacy
                    if 'responses' in cat_data:
                        del cat_data['responses']
                    if 'distribution' in cat_data:
                        del cat_data['distribution']

    return filtered_data


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
            question_type = question_data.get('question_type')

            # Process numeric questions: rating, scale, and choice questions with scoring
            if question_type == 'rating' or question_type == 'scale':
                # Direct numeric types
                pass
            elif question_type in ['single_choice', 'multiple_choice']:
                # Only include if scoring is enabled
                config = question_data.get('question_config', {})
                if not config.get('scoring_enabled'):
                    continue
            else:
                # Skip text, likert (text-based), and other non-numeric types
                continue

            for category, cat_data in question_data.get('by_category', {}).items():
                # Statistical validity check: need 2+ responses for meaningful average
                # Exception: self and manager categories can use 1+ (single assessor)
                count = cat_data.get('count', 0)
                min_valid = 1 if category in ['self', 'manager'] else 2
                if count < min_valid:
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
    # Ensure 'self' is always listed first
    section_summary = {}
    category_order = ['self', 'peer', 'manager', 'direct_report']

    for section_title, categories in section_averages.items():
        section_summary[section_title] = {}

        # Add categories in order (self first)
        for category in category_order:
            if category in categories and categories[category]:
                section_summary[section_title][category] = round(mean(categories[category]), 2)

        # Add any remaining categories not in the standard list
        for category, ratings in categories.items():
            if category not in category_order and ratings:
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
                    'self_score': round(self_avg, 2),
                    'others_score': round(others_avg, 2),
                    'gap': round(gap, 2),
                    'message': f'Self-assessment ({self_avg:.1f}) significantly lower than others\' perception ({others_avg:.1f})',
                    'interpretation': 'Strong performance but may undervalue own contributions'
                })
            elif gap > 0.5:
                insights['perception_gaps'].append({
                    'type': 'overconfidence',
                    'severity': 'high' if gap > 1.0 else 'moderate',
                    'self_score': round(self_avg, 2),
                    'others_score': round(others_avg, 2),
                    'gap': round(gap, 2),
                    'message': f'Self-assessment ({self_avg:.1f}) higher than others\' perception ({others_avg:.1f})',
                    'interpretation': 'Opportunity to align self-perception with team feedback'
                })

    # Identify strengths (avg >= 4.0) and development areas (avg < 3.0)
    for section_title, categories in section_summary.items():
        # Use non-self categories for strengths/weaknesses
        relevant_scores = [v for k, v in categories.items() if k != 'self']
        if relevant_scores:
            avg_score = mean(relevant_scores)
            self_score = categories.get('self')

            if avg_score >= 4.0:
                strength = {
                    'area': section_title,
                    'others_avg': round(avg_score, 2),
                    'level': 'exceptional' if avg_score >= 4.5 else 'strong'
                }
                # Add self score and gap if available
                if self_score is not None:
                    strength['self_score'] = self_score
                    strength['gap'] = round(self_score - avg_score, 2)
                insights['strengths'].append(strength)

            elif avg_score < 3.0:
                dev_area = {
                    'area': section_title,
                    'others_avg': round(avg_score, 2),
                    'priority': 'high' if avg_score < 2.5 else 'medium'
                }
                # Add self score and gap if available
                if self_score is not None:
                    dev_area['self_score'] = self_score
                    dev_area['gap'] = round(self_score - avg_score, 2)
                insights['development_areas'].append(dev_area)

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

    # Overall sentiment - based on others only (exclude self)
    others_ratings = all_peer_ratings + all_manager_ratings
    if others_ratings:
        overall_avg = mean(others_ratings)
        insights['overall_sentiment'] = {
            'score': round(overall_avg, 2),
            'rating': 'Outstanding' if overall_avg >= 4.5 else
                     'Excellent' if overall_avg >= 4.0 else
                     'Strong' if overall_avg >= 3.5 else
                     'Developing' if overall_avg >= 3.0 else
                     'Needs Support',
            'based_on': 'others',  # Clarify this excludes self
            'self_avg': round(mean(all_self_ratings), 2) if all_self_ratings else None
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
            question_type = question_data.get('question_type')

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

            # Process numeric questions for charts: rating, scale, and choice questions with scoring
            if question_type == 'rating' or question_type == 'scale':
                # Direct numeric types
                pass
            elif question_type in ['single_choice', 'multiple_choice']:
                # Only include if scoring is enabled
                config = question_data.get('question_config', {})
                if not config.get('scoring_enabled'):
                    continue
            else:
                # Skip text, likert (text-based), and other non-numeric types
                continue

            for category, cat_data in question_data.get('by_category', {}).items():
                # Statistical validity check: need 2+ responses for meaningful average
                # Exception: self and manager categories can use 1+ (single assessor)
                count = cat_data.get('count', 0)
                min_valid = 1 if category in ['self', 'manager'] else 2
                if count < min_valid:
                    continue

                avg = cat_data.get('avg')
                if avg is not None:
                    # Normalize to 1-5 scale for consistent charting
                    normalized_avg = avg

                    if question_type == 'scale':
                        # Scale questions may have different ranges - normalize to 1-5
                        try:
                            config = question_data.get('question_config', {})
                            min_val = config.get('min', 1)
                            max_val = config.get('max', 100)

                            if max_val > min_val:
                                # Normalize: 1 + ((value - min) / (max - min)) * 4
                                normalized_avg = 1 + ((avg - min_val) / (max_val - min_val)) * 4
                        except (KeyError, ZeroDivisionError, TypeError):
                            # If normalization fails, use raw value
                            pass

                    elif question_type in ['single_choice', 'multiple_choice']:
                        # Choice questions with weights - normalize based on weight range
                        try:
                            config = question_data.get('question_config', {})
                            weights = config.get('weights', [])

                            if weights:
                                min_weight = min(weights)
                                max_weight = max(weights)

                                if max_weight > min_weight:
                                    # Normalize: 1 + ((value - min) / (max - min)) * 4
                                    normalized_avg = 1 + ((avg - min_weight) / (max_weight - min_weight)) * 4
                        except (KeyError, ZeroDivisionError, TypeError, ValueError):
                            # If normalization fails, use raw value
                            pass

                    section_scores[category]['total'] += normalized_avg * chart_weight
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
            'question_config': {},
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
        question_data['question_config'] = question.config  # Store config for weight calculations

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
            # Ensure 'self' category is always first in output
            category_order = ['self', 'peer', 'manager', 'direct_report']
            ordered_categories = {}

            # Add categories in order (self first)
            for category in category_order:
                if category in question_data['by_category']:
                    ordered_categories[category] = question_data['by_category'][category]

            # Add any remaining categories not in standard list
            for category, category_data in question_data['by_category'].items():
                if category not in category_order:
                    ordered_categories[category] = category_data

            # Store category order explicitly (PostgreSQL JSONB doesn't preserve dict order)
            present_categories = [cat for cat in category_order if cat in ordered_categories]
            present_categories.extend([cat for cat in ordered_categories.keys() if cat not in category_order])

            report_question = {
                'question_text': question_data['question_text'],
                'question_type': question_data['question_type'],
                'category_order': present_categories,  # Explicit ordering
                'by_category': {}
            }

            for category, category_data in ordered_categories.items():
                count = category_data['count']

                # Store all data without anonymization filtering
                # Anonymization will be applied at display layer
                result = {
                    'count': count,
                    'responses': category_data['responses']
                }

                # Calculate average for rating, scale, and likert questions
                if question_data['question_type'] == 'rating':
                    numeric_responses = [r for r in category_data['responses'] if isinstance(r, (int, float))]
                    if numeric_responses:
                        result['avg'] = round(sum(numeric_responses) / len(numeric_responses), 2)
                elif question_data['question_type'] == 'scale':
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
                elif question_data['question_type'] == 'single_choice':
                    # Store distribution of single choice responses (dropdown selection)
                    from collections import Counter
                    text_responses = [r for r in category_data['responses'] if r]
                    if text_responses:
                        result['distribution'] = dict(Counter(text_responses))

                        # Calculate weighted score if weights are configured
                        config = question_data.get('question_config', {})
                        if config.get('scoring_enabled') and config.get('weights'):
                            choices = config.get('choices', [])
                            weights = config.get('weights', [])
                            scores = []

                            for response_text in text_responses:
                                try:
                                    # Find the index of the selected choice
                                    choice_index = choices.index(response_text)
                                    if 0 <= choice_index < len(weights):
                                        scores.append(weights[choice_index])
                                except (ValueError, IndexError):
                                    pass  # Skip if choice not found or index out of range

                            if scores:
                                result['avg'] = round(sum(scores) / len(scores), 2)

                elif question_data['question_type'] == 'multiple_choice':
                    # Store distribution of multiple choice responses (checkboxes)
                    # Each response is a list of selected options, so we need to flatten
                    from collections import Counter
                    all_selected_options = []
                    for response in category_data['responses']:
                        if response and isinstance(response, list):
                            all_selected_options.extend(response)
                    if all_selected_options:
                        result['distribution'] = dict(Counter(all_selected_options))

                        # Calculate weighted score if weights are configured
                        config = question_data.get('question_config', {})
                        if config.get('scoring_enabled') and config.get('weights'):
                            choices = config.get('choices', [])
                            weights = config.get('weights', [])
                            response_scores = []

                            # For each response (which is a list of selected choices)
                            for response in category_data['responses']:
                                if response and isinstance(response, list):
                                    selected_weights = []
                                    for selected_choice in response:
                                        try:
                                            choice_index = choices.index(selected_choice)
                                            if 0 <= choice_index < len(weights):
                                                selected_weights.append(weights[choice_index])
                                        except (ValueError, IndexError):
                                            pass

                                    # Sum the weights for this response (not average)
                                    # This rewards selecting more positive attributes
                                    if selected_weights:
                                        response_scores.append(sum(selected_weights))

                            # Average all response scores
                            if response_scores:
                                result['avg'] = round(sum(response_scores) / len(response_scores), 2)

                # Add to ordered dict (maintains insertion order in Python 3.7+)
                report_question['by_category'][category] = result

            report_section['questions'][str(question_id)] = report_question

        report_data['by_section'][str(section_id)] = report_section

    # Generate insights and analytics
    insights, section_summary = _calculate_insights(report_data)
    report_data['insights'] = insights
    report_data['section_summary'] = section_summary

    # Generate chart data
    chart_data = _calculate_chart_data(report_data, cycle)
    report_data['charts'] = chart_data

    # Add cycle-over-cycle comparison if previous cycle exists
    previous_report = _get_previous_cycle_report(cycle)

    # Count historical cycles for this reviewee with same questionnaire
    historical_cycle_count = ReviewCycle.objects.filter(
        reviewee=cycle.reviewee,
        questionnaire=cycle.questionnaire,
        status='completed',
        created_at__lt=cycle.created_at
    ).count()

    if previous_report:
        comparison_data = {
            'has_previous': True,
            'previous_cycle_date': previous_report.cycle.created_at.strftime('%Y-%m-%d'),
            'section_trends': {},
            'overall_trend': None,
            'show_trends': historical_cycle_count >= 2  # Only show trends with 3+ total data points
        }

        # Compare section scores
        prev_section_summary = previous_report.report_data.get('section_summary', {})
        for section_name, categories in section_summary.items():
            if section_name in prev_section_summary:
                current_others = [v for k, v in categories.items() if k != 'self']
                prev_categories = prev_section_summary[section_name]
                prev_others = [v for k, v in prev_categories.items() if k != 'self']

                if current_others and prev_others:
                    current_avg = mean(current_others)
                    prev_avg = mean(prev_others)
                    trend = _calculate_trend_indicator(current_avg, prev_avg)
                    if trend:
                        comparison_data['section_trends'][section_name] = trend

        # Compare overall performance
        if insights:
            current_overall = insights.get('overall_sentiment', {}).get('score') if insights.get('overall_sentiment') else None
            prev_insights = previous_report.report_data.get('insights', {})
            prev_overall = prev_insights.get('overall_sentiment', {}).get('score') if prev_insights and prev_insights.get('overall_sentiment') else None
            if current_overall and prev_overall:
                comparison_data['overall_trend'] = _calculate_trend_indicator(current_overall, prev_overall)

        report_data['comparison'] = comparison_data
    else:
        report_data['comparison'] = {
            'has_previous': False,
            'show_trends': False
        }

    # Add peer benchmarks
    peer_benchmarks = _calculate_peer_benchmarks(cycle, section_summary)
    if peer_benchmarks:
        report_data['peer_benchmarks'] = peer_benchmarks
    else:
        report_data['peer_benchmarks'] = None

    # Generate access token if needed (before save to trigger webhook correctly)
    import uuid
    try:
        existing_report = Report.objects.get(cycle=cycle)
        access_token = existing_report.access_token or uuid.uuid4()
    except Report.DoesNotExist:
        access_token = uuid.uuid4()

    # Create or update report with access_token included
    report, created = Report.objects.update_or_create(
        cycle=cycle,
        defaults={
            'report_data': report_data,
            'available': True,
            'access_token': access_token
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
        base_url = f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}"

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
