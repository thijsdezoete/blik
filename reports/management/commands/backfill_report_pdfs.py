"""
One-time backfill after the PDF export ships: every finalised completed cycle gets a report and a stored PDF.
It never sends an email. Running it again changes nothing.

Usage:
    python manage.py backfill_report_pdfs            # Build reports and PDFs
    python manage.py backfill_report_pdfs --dry-run  # Count what is missing
    python manage.py backfill_report_pdfs --regenerate  # Recalculate every report and rebuild its PDF
"""
from django.core.management.base import BaseCommand, CommandError

from reports.models import Report
from reports.pdf import store_report_pdf
from reports.services import generate_report
from reviews.models import ReviewCycle


class Command(BaseCommand):
    help = 'Build the report and the stored PDF of every completed cycle that lacks one'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show how much is missing without changing anything',
        )

        parser.add_argument(
            '--regenerate',
            action='store_true',
            help='Recalculate existing reports from their stored answers and rebuild their PDFs',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        regenerate = options['regenerate']
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN -- nothing will be changed\n'))

        reports_made = reports_recalculated = pdfs_stored = 0
        errors = []
        # Unfinalised cycles belong to finalize_reports, which also sends the reviewee's email
        cycles = ReviewCycle.objects.filter(status='completed', report_finalized_at__isnull=False)
        # A report's trend reads the report of the previous cycle, which that lookup finds by created_at.
        # Oldest first means every trend sees an already recalculated report.
        cycles = cycles.order_by('created_at', 'pk') if regenerate else cycles.order_by('pk')
        for cycle in cycles:
            try:
                report = Report.objects.filter(cycle=cycle).first()
                if dry_run:
                    reports_made += report is None
                    reports_recalculated += regenerate and report is not None
                    pdfs_stored += regenerate or report is None or not report.has_valid_pdf()
                    continue
                if report is None or regenerate:
                    # generate_report sends no email and drops the old PDF
                    existed = report is not None
                    report = generate_report(cycle)
                    reports_made += not existed
                    reports_recalculated += existed
                if not report.has_valid_pdf():
                    store_report_pdf(report)
                    pdfs_stored += 1
            except Exception as e:
                errors.append(f'Cycle {cycle.pk}: {e}')

        verb = 'to do' if dry_run else 'done'
        self.stdout.write(f'Reports created: {reports_made} {verb}')
        if regenerate:
            self.stdout.write(f'Reports recalculated: {reports_recalculated} {verb}')
        self.stdout.write(f'PDFs stored: {pdfs_stored} {verb}')
        for error in errors:
            self.stderr.write(error)
        if errors:
            raise CommandError(f'{len(errors)} cycle(s) failed')
