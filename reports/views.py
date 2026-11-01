from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.decorators.http import require_http_methods
from django.utils.translation import gettext as _
from accounts.permissions import can_view_all_reports, reviewee_emails_below
from reviews.models import ReviewCycle
from .models import Report
from .report_texts import with_texts
from .services import generate_report, get_report_summary, apply_display_anonymization
import uuid


def get_cycle_or_404(request, cycle_uuid):
    """
    Get a cycle for the admin report views: must be in the user's organization,
    and the user must be an org admin. A cycle UUID alone is not authorization —
    without the org check any admin could read another organization's report.
    """
    cycle = get_object_or_404(
        ReviewCycle.objects.select_related('reviewee', 'questionnaire'),
        uuid=cycle_uuid
    )
    in_org = (not request.organization
              or cycle.reviewee.organization_id == request.organization.id)
    if not in_org or not can_view_report(request, cycle):
        raise Http404
    return cycle


def can_view_report(request, cycle):
    return can_view_all_reports(request.user) or (
        cycle.reviewee.email.lower() in reviewee_emails_below(request.user, request.organization)
    )


def is_own_cycle(user, cycle):
    """Reviewees are matched by email — there is no FK from Reviewee to User."""
    return bool(user.email) and cycle.reviewee.email.lower() == user.email.lower()


@login_required
def view_report(request, cycle_uuid):
    """View aggregated feedback report for a review cycle (org admins and managers above the reviewee)"""
    # Reviewees reach their own report through the token URL, not the admin view.
    cycle = get_object_or_404(ReviewCycle.objects.select_related('reviewee'), uuid=cycle_uuid)
    if not can_view_report(request, cycle):
        if not is_own_cycle(request.user, cycle):
            raise Http404
        report = Report.objects.filter(cycle=cycle).first() or generate_report(cycle)
        return redirect('reports:reviewee_report', access_token=report.access_token)

    cycle = get_cycle_or_404(request, cycle_uuid)

    # Get or generate report
    try:
        report = Report.objects.get(cycle=cycle)
    except Report.DoesNotExist:
        report = generate_report(cycle)

    summary = get_report_summary(report)

    # Apply display-level anonymization based on organization settings
    min_threshold = cycle.organization.min_responses_for_anonymity
    report_data = with_texts(report.report_data, cycle.questionnaire, cycle.reviewee.name)
    display_data = apply_display_anonymization(
        report_data,
        min_threshold=min_threshold
    )

    context = {
        'cycle': cycle,
        'report': report,
        'report_data': report_data,
        'display_data': display_data,  # For detailed report sections
        'summary': summary,
        'questionnaire': cycle.questionnaire.translated(),
        'is_admin_view': True,
        # A manager reads the report but does not run the cycle.
        'is_manager_view': not can_view_all_reports(request.user),
    }

    return render(request, 'reports/view_report.html', context)


@login_required
def regenerate_report(request, cycle_uuid):
    """Regenerate report for a review cycle"""
    cycle = get_cycle_or_404(request, cycle_uuid)
    if not can_view_all_reports(request.user):
        raise Http404
    generate_report(cycle)

    return redirect('reports:view_report', cycle_uuid=cycle.uuid)


def reviewee_report(request, access_token):
    """Public-facing report view for reviewees - secured by UUID token"""
    from django.utils import timezone

    # Get report by access token
    try:
        report = Report.objects.select_related(
            'cycle__reviewee',
            'cycle__questionnaire'
        ).get(access_token=access_token)
    except Report.DoesNotExist:
        return render(request, 'reports/access_denied.html', status=403)

    # Check if access token has expired
    if report.access_token_expired:
        return render(request, 'reports/access_denied.html', {
            'error': _('This report link has expired. Please contact your administrator for a new link.')
        }, status=403)

    # Log access for security auditing
    report.last_accessed = timezone.now()
    report.access_count += 1
    report.save(update_fields=['last_accessed', 'access_count'])

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

    # Apply display-level anonymization based on organization settings
    min_threshold = cycle.organization.min_responses_for_anonymity
    report_data = with_texts(report.report_data, cycle.questionnaire, cycle.reviewee.name)
    display_data = apply_display_anonymization(
        report_data,
        min_threshold=min_threshold
    )

    context = {
        'cycle': cycle,
        'report': report,
        'report_data': report_data,
        'display_data': display_data,  # For detailed report sections
        'summary': summary,
        'questionnaire': cycle.questionnaire.translated(),
        'is_public_view': True,
    }

    return render(request, 'reports/reviewee_report.html', context)
