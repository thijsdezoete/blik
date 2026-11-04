"""
Finalise completed cycles off the request path: the report, its stored PDF and the report-ready email.

The finalize_reports cron command runs this for every completed cycle without report_finalized_at.
Cycles completed before this existed have report_finalized_at set by a migration, so they never get an email.
"""
import logging

from django.db.models import Max
from django.utils import timezone

from reviews.models import ReviewCycle

from .models import Report
from .pdf import drop_report_pdf, store_report_pdf
from .services import generate_report, send_report_ready_notification

logger = logging.getLogger(__name__)

MAX_PDF_ATTEMPTS = 3


def cycles_to_finalize():
    return ReviewCycle.objects.filter(status='completed', report_finalized_at__isnull=True)


def finalize_cycle(cycle, *, force_send=False):
    """
    Make sure the cycle has a current report and a stored PDF, and send the report-ready email when wanted.

    Returns 'sent', 'sent_without_pdf', 'waiting_for_pdf', 'finalized' (no email to send) or 'failed'.
    force_send is an admin's explicit action: it sends even with auto_send_report_email off, and doesn't
    hold the email back for a failed PDF, because the admin expects the email now.
    """
    report = _current_report(cycle)

    if not report.has_valid_pdf():
        try:
            store_report_pdf(report)
            report.pdf_attempts = 0
        except Exception:
            report.pdf_attempts += 1
            logger.exception('PDF build failed for cycle %s (attempt %s)', cycle.id, report.pdf_attempts)
        report.save(update_fields=['pdf_attempts'])

    organization = cycle.organization
    result = 'finalized'
    if force_send or organization.auto_send_report_email:
        has_pdf = report.has_valid_pdf()
        if (organization.attach_report_pdf and not has_pdf and not force_send
                and report.pdf_attempts < MAX_PDF_ATTEMPTS):
            return 'waiting_for_pdf'
        pdf = None
        if organization.attach_report_pdf and has_pdf:
            with report.pdf_file.open('rb') as stored:
                pdf = stored.read()
        stats = send_report_ready_notification(report, pdf=pdf)
        if not stats['sent']:
            logger.error('Report email for cycle %s not sent: %s', cycle.id, stats['errors'])
            return 'failed'
        result = 'sent' if pdf else 'sent_without_pdf'
        if not pdf and organization.attach_report_pdf:
            logger.error('Report email for cycle %s sent without the PDF: the build failed', cycle.id)

    # An admin can send the report of an active cycle; the cron finalises it again once the cycle completes.
    if cycle.status == 'completed':
        cycle.report_finalized_at = timezone.now()
        cycle.save(update_fields=['report_finalized_at'])
    return result


def _current_report(cycle):
    """The cycle's report, generated again when a submission came in after it was generated."""
    report = Report.objects.filter(cycle=cycle).first()
    last_submission = cycle.tokens.aggregate(last=Max('completed_at'))['last']
    if report is None or (last_submission and report.updated_at < last_submission):
        report = generate_report(cycle)
    return report


def delete_expired_pdfs(now=None):
    """Delete stored PDFs past their retention period. Returns how many."""
    now = now or timezone.now()
    deleted = 0
    for report in Report.objects.exclude(pdf_file='').select_related('cycle__reviewee__organization'):
        if report.pdf_expires_at is None or report.pdf_expires_at <= now:
            drop_report_pdf(report)
            deleted += 1
    return deleted
