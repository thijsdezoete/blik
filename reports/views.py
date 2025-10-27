from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from accounts.permissions import can_manage_organization_required
from reviews.models import ReviewCycle
from .models import Report
from .services import generate_report, get_report_summary
import uuid


@login_required
@can_manage_organization_required
def view_report(request, cycle_id):
    """View aggregated feedback report for a review cycle"""
    cycle = get_object_or_404(ReviewCycle, id=cycle_id)

    # Get or generate report
    try:
        report = Report.objects.get(cycle=cycle)
    except Report.DoesNotExist:
        report = generate_report(cycle)

    summary = get_report_summary(report)

    context = {
        'cycle': cycle,
        'report': report,
        'summary': summary,
        'questionnaire': cycle.questionnaire,
    }

    return render(request, 'reports/view_report.html', context)


@login_required
@can_manage_organization_required
def regenerate_report(request, cycle_id):
    """Regenerate report for a review cycle"""
    cycle = get_object_or_404(ReviewCycle, id=cycle_id)
    generate_report(cycle)

    return redirect('reports:view_report', cycle_id=cycle_id)


def reviewee_report(request, access_token):
    """Public-facing report view for reviewees - secured by UUID token"""

    # Get report by access token
    try:
        report = Report.objects.select_related(
            'cycle__reviewee',
            'cycle__questionnaire'
        ).get(access_token=access_token)
    except Report.DoesNotExist:
        return render(request, 'reports/access_denied.html', status=403)

    cycle = report.cycle

    # Check if report is available (cycle should be completed)
    # Org admins can bypass this check
    can_bypass = (request.user.is_authenticated and
                  request.user.has_perm('accounts.can_manage_organization'))
    if cycle.status != 'completed' and not can_bypass:
        return render(request, 'reports/report_not_ready.html', {
            'cycle': cycle,
        })

    summary = get_report_summary(report)

    context = {
        'cycle': cycle,
        'report': report,
        'summary': summary,
        'questionnaire': cycle.questionnaire,
        'is_public_view': True,
    }

    return render(request, 'reports/reviewee_report.html', context)
