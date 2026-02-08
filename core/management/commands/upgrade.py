"""
Run pending one-time upgrade steps.

Usage:
    python manage.py upgrade            # Run all pending steps
    python manage.py upgrade --list     # Show status of all steps
    python manage.py upgrade --dry-run  # Preview without running
"""
import sys
import traceback

from django.core.management.base import BaseCommand

from core.models import UpgradeStep
from core.upgrade_steps import STEPS


class Command(BaseCommand):
    help = 'Run pending one-time upgrade steps'

    def add_arguments(self, parser):
        parser.add_argument(
            '--list',
            action='store_true',
            help='Show status of all registered steps',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview pending steps without running them',
        )

    def handle(self, *args, **options):
        if options['list']:
            return self._list_steps()

        completed = set(
            UpgradeStep.objects.filter(success=True).values_list('name', flat=True)
        )

        pending = [(name, fn) for name, fn in STEPS if name not in completed]

        if not pending:
            self.stdout.write(self.style.SUCCESS('All upgrade steps are up to date.'))
            return

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('DRY RUN -- no steps will be executed\n'))
            for name, _ in pending:
                self.stdout.write(f'  Pending: {name}')
            return

        for name, fn in pending:
            self.stdout.write(f'Running {name}...')

            # Remove any prior failed record so we get a fresh row
            UpgradeStep.objects.filter(name=name, success=False).delete()

            try:
                fn(self.stdout)
                UpgradeStep.objects.create(name=name, success=True)
                self.stdout.write(self.style.SUCCESS(f'  {name} OK'))
            except Exception:
                tb = traceback.format_exc()
                UpgradeStep.objects.create(name=name, success=False, error=tb)
                self.stderr.write(self.style.ERROR(f'  {name} FAILED'))
                self.stderr.write(tb)
                sys.exit(1)

        self.stdout.write(self.style.SUCCESS(
            f'\nAll upgrade steps complete ({len(pending)} applied).'
        ))

    def _list_steps(self):
        records = {s.name: s for s in UpgradeStep.objects.all()}

        self.stdout.write(f'{"Step":<40} {"Status":<10} {"Applied at"}')
        self.stdout.write('-' * 70)

        for name, _ in STEPS:
            record = records.get(name)
            if record and record.success:
                status = self.style.SUCCESS('OK')
                applied = str(record.applied_at.strftime('%Y-%m-%d %H:%M'))
            elif record:
                status = self.style.ERROR('FAILED')
                applied = str(record.applied_at.strftime('%Y-%m-%d %H:%M'))
            else:
                status = self.style.WARNING('PENDING')
                applied = ''
            self.stdout.write(f'{name:<40} {status:<10} {applied}')
