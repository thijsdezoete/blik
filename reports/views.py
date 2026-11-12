from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.decorators.http import require_http_methods
from django.utils import translation
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit
from accounts.permissions import can_view_all_reports, direct_report_emails
from reviews.models import ReviewCycle
from .models import Report
from .context import build_report_context
from .pdf import pdf_response, render_report_pdf, reviewee_language, store_report_pdf, stored_pdf_bytes
from .services import generate_report
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
        cycle.reviewee.email.lower() in direct_report_emails(request.user, request.organization)
    )


def is_own_cycle(user, cycle):
    """
    Reviewees are matched by email — there is no FK from Reviewee to User — and
    only inside the user's own organization: emails are not unique across tenants.
    """
    profile = getattr(user, 'profile', None)
    return (
        bool(user.email)
        and profile is not None
        and cycle.reviewee.organization_id == profile.organization_id
        and cycle.reviewee.email.lower() == user.email.lower()
    )


@login_required
def view_report(request, cycle_uuid):
    """View aggregated feedback report for a review cycle (org admins and the reviewee's direct manager)"""
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

    context = build_report_context(report, is_admin_view=True)
    context['pdf_valid'] = report.has_valid_pdf()
    # A manager reads the report but does not run the cycle.
    context['is_manager_view'] = not can_view_all_reports(request.user)

    return render(request, 'reports/view_report.html', context)


@login_required
def regenerate_report(request, cycle_uuid):
    """Regenerate report for a review cycle"""
    cycle = get_cycle_or_404(request, cycle_uuid)
    if not can_view_all_reports(request.user):
        raise Http404
    generate_report(cycle)

    return redirect('reports:view_report', cycle_uuid=cycle.uuid)


def _reviewee_report_or_response(request, access_token):
    """The report behind a reviewee token, or the response that refuses it."""
    from django.utils import timezone

    # Get report by access token
    try:
        report = Report.objects.select_related(
            'cycle__reviewee',
            'cycle__questionnaire'
        ).get(access_token=access_token)
    except Report.DoesNotExist:
        return None, render(request, 'reports/access_denied.html', status=403)

    # Check if access token has expired
    if report.access_token_expired:
        return None, render(request, 'reports/access_denied.html', {
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
        return None, render(request, 'reports/report_not_ready.html', {
            'cycle': cycle,
        })
    return report, None


def reviewee_report(request, access_token):
    """Public-facing report view for reviewees - secured by UUID token"""
    report, refusal = _reviewee_report_or_response(request, access_token)
    if refusal:
        return refusal

    context = build_report_context(report, is_admin_view=False)
    context['is_public_view'] = True
    context['pdf_valid'] = report.has_valid_pdf()

    return render(request, 'reports/reviewee_report.html', context)


@ratelimit(key='ip', rate='10/h', method='POST', block=True)
def reviewee_report_pdf(request, access_token):
    """Download (GET) or regenerate (POST) the stored PDF behind a reviewee token"""
    report, refusal = _reviewee_report_or_response(request, access_token)
    if refusal:
        return refusal

    # The stored file is in the reviewee's language; a reader in another one gets a fresh render
    language = translation.get_language()
    if language != reviewee_language(report):
        return pdf_response(report, render_report_pdf(report, language))

    if request.method == 'POST':
        store_report_pdf(report)
    elif not report.has_valid_pdf():
        # The report page offers "Regenerate PDF"
        return redirect('reports:reviewee_report', access_token=access_token)
    return pdf_response(report, stored_pdf_bytes(report))


@login_required
@require_http_methods(['GET', 'POST'])
def report_pdf(request, cycle_uuid):
    """Download (GET) or regenerate (POST) the report PDF (org admins only)"""
    if not can_view_all_reports(request.user):
        cycle = get_object_or_404(
            ReviewCycle.objects.select_related('reviewee'), uuid=cycle_uuid
        )
        if not is_own_cycle(request.user, cycle):
            raise Http404
        report = Report.objects.filter(cycle=cycle).first() or generate_report(cycle)
        return redirect('reports:reviewee_report_pdf', access_token=report.access_token)

    cycle = get_cycle_or_404(request, cycle_uuid)
    try:
        report = Report.objects.get(cycle=cycle)
    except Report.DoesNotExist:
        report = generate_report(cycle)

    # A stored file is in the reviewee's language; an admin in another one gets a fresh render
    language = translation.get_language()
    if language != reviewee_language(report):
        return pdf_response(report, render_report_pdf(report, language))

    if request.method == 'POST':
        store_report_pdf(report)
    elif not report.has_valid_pdf():
        return redirect('reports:view_report', cycle_uuid=cycle.uuid)
    return pdf_response(report, stored_pdf_bytes(report))
