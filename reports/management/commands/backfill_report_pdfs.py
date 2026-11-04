"""
One-time backfill after the PDF export ships: every completed cycle gets a report, a stored PDF
and a finalised date. It never sends an email. Running it again changes nothing.

Usage:
    python manage.py backfill_report_pdfs            # Build reports and PDFs
    python manage.py backfill_report_pdfs --dry-run  # Count what is missing
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

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

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN -- nothing will be changed\n'))

        reports_made = pdfs_stored = finalized = 0
        errors = []
        for cycle in ReviewCycle.objects.filter(status='completed').order_by('pk'):
            try:
                report = Report.objects.filter(cycle=cycle).first()
                if report is None:
                    if not dry_run:
                        # generate_report sends no email; the follow-up emails are not touched
                        report = generate_report(cycle)
                    reports_made += 1
                if report is None or not report.has_valid_pdf():
                    if not dry_run:
                        store_report_pdf(report)
                    pdfs_stored += 1
                if cycle.report_finalized_at is None:
                    if not dry_run:
                        cycle.report_finalized_at = timezone.now()
                        cycle.save(update_fields=['report_finalized_at'])
                    finalized += 1
            except Exception as e:
                errors.append(f'Cycle {cycle.pk}: {e}')

        verb = 'to do' if dry_run else 'done'
        self.stdout.write(f'Reports created: {reports_made} {verb}')
        self.stdout.write(f'PDFs stored: {pdfs_stored} {verb}')
        self.stdout.write(f'Cycles finalised: {finalized} {verb}')
        for error in errors:
            self.stdout.write(self.style.ERROR(error))
