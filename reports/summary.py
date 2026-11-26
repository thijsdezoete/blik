from datetime import date

from django.db.models import Count, Q

from .context import build_report_context
from .models import Report
from .services import self_vs_others_gap


def reviewee_summary(reviewee, reader):
    """
    The reviews of a reviewee, newest first, and the numbers of the latest report.

    reader is 'all', 'manager' or 'own'. Each gets the display data of the report page they
    can open: view_report gives an admin and a manager the admin view, the reviewee's link
    gives the reviewee's view. A number that view leaves out is None here.
    """
    threshold = reviewee.organization.min_responses_for_anonymity
    cycles = reviewee.review_cycles.select_related('questionnaire', 'reviewee__organization').annotate(
        invited=Count('tokens'),
        answered=Count('tokens', filter=Q(tokens__completed_at__isnull=False)),
    ).order_by('-created_at', '-pk')
    # The rule of the reviewee list: a report shows once its cycle is completed
    reports = {
        report.cycle_id: report
        for report in Report.objects.filter(cycle__reviewee=reviewee, cycle__status='completed', available=True)
    }

    reviews = []
    latest = None
    for cycle in cycles:
        report = reports.get(cycle.pk)
        display_data = None
        if report:
            report.cycle = cycle
            display_data = build_report_context(report, is_admin_view=reader != 'own')['display_data']
            if latest is None:
                latest = (report, display_data)
        reviews.append({
            'cycle': cycle,
            'report': report,
            'answered': cycle.answered,
            'invited': cycle.invited,
            'score': _score(display_data),
        })

    summary = {'reviews': reviews, 'latest_score': None, 'change': None, 'change_since': None, 'gap': None}
    if latest:
        report, display_data = latest
        comparison = display_data.get('comparison') or {}
        change = (comparison.get('overall_trend') or {}).get('change')
        summary.update({
            'latest_score': _score(display_data),
            'change': change,
            # The date of the review the change compares with, as the report generation stored it
            'change_since': date.fromisoformat(comparison['previous_cycle_date']) if change is not None else None,
            'gap': self_vs_others_gap(report.report_data, threshold),
        })
    return summary


def _score(display_data):
    sentiment = ((display_data or {}).get('insights') or {}).get('overall_sentiment') or {}
    return sentiment.get('score')
