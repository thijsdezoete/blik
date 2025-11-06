"""
Management command to regenerate reports that are missing the category_order field
"""
from django.core.management.base import BaseCommand
from reports.models import Report
from reports.services import generate_report


class Command(BaseCommand):
    help = 'Regenerate reports missing category_order field to fix category ordering'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without actually updating',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Find all reports without category_order
        reports_to_fix = []

        all_reports = Report.objects.all().select_related('cycle__reviewee')

        for report in all_reports:
            by_section = report.report_data.get('by_section', {})
            if by_section:
                first_section = list(by_section.values())[0]
                first_q = list(first_section['questions'].values())[0]

                if first_q.get('category_order') is None:
                    reports_to_fix.append(report)

        if not reports_to_fix:
            self.stdout.write(self.style.SUCCESS('All reports already have category_order field'))
            return

        self.stdout.write(f'Found {len(reports_to_fix)} reports to fix')

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made'))
            for report in reports_to_fix:
                self.stdout.write(f'  Would fix: Report {report.id} (Cycle {report.cycle.id}, {report.cycle.reviewee.name})')
            return

        # Regenerate each report
        success_count = 0
        error_count = 0

        for report in reports_to_fix:
            try:
                self.stdout.write(f'Regenerating report {report.id} (Cycle {report.cycle.id})...', ending='')
                generate_report(report.cycle)
                success_count += 1
                self.stdout.write(self.style.SUCCESS(' ✓'))
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f' ✗ Error: {e}'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Successfully fixed {success_count} reports'))

        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'Failed to fix {error_count} reports'))
