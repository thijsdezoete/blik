"""
Finalise completed review cycles: generate the report, store its PDF and send the report-ready email.
Also deletes stored PDFs past their retention period.

The last reviewer's submit only closes the cycle, so it stays fast. Runs every 5 minutes via cron:
    python manage.py finalize_reports
"""
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from notifications.log import record_run
from reports.finalize import cycles_to_finalize, delete_expired_pdfs, finalize_cycle

logger = logging.getLogger('reports.finalize')


class Command(BaseCommand):
    help = 'Generate, store and email the reports of completed review cycles'

    def handle(self, *args, **options):
        sent = 0
        errors = []
        for cycle_id in list(cycles_to_finalize().values_list('id', flat=True)):
            try:
                with transaction.atomic():
                    # Skip a cycle another run (or an admin) is finalising right now
                    cycle = cycles_to_finalize().select_for_update(skip_locked=True).filter(id=cycle_id).first()
                    if cycle is None:
                        continue
                    result = finalize_cycle(cycle)
            except Exception as e:
                logger.exception('Finalising cycle %s failed', cycle_id)
                errors.append(f'Cycle {cycle_id}: {e}')
                continue
            if result in ('sent', 'sent_without_pdf'):
                sent += 1
            elif result == 'failed':
                errors.append(f'Cycle {cycle_id}: report email not sent')
            self.stdout.write(f'Cycle {cycle_id}: {result}')

        deleted = delete_expired_pdfs()
        if deleted:
            self.stdout.write(f'Deleted {deleted} expired PDFs')

        record_run('finalize_reports', sent, errors)

        for error in errors:
            self.stderr.write(self.style.ERROR(f'  {error}'))
