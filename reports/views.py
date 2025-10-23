from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from reviews.models import ReviewCycle
from .models import Report
from .services import generate_report, get_report_summary


@staff_member_required
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


@staff_member_required
def regenerate_report(request, cycle_id):
    """Regenerate report for a review cycle"""
    cycle = get_object_or_404(ReviewCycle, id=cycle_id)
    generate_report(cycle)

    return redirect('reports:view_report', cycle_id=cycle_id)
