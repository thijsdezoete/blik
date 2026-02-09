"""
Send close check-in emails for review cycles that use invite links.

Designed to run daily via cron:
    python manage.py send_cycle_reminders

Usage:
    python manage.py send_cycle_reminders            # Send emails
    python manage.py send_cycle_reminders --dry-run   # Preview without sending
"""
from django.core.management.base import BaseCommand

from reviews.services import send_close_check_emails


class Command(BaseCommand):
    help = 'Send close check-in emails for invite-link review cycles open 7+ days'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show eligible cycles without sending emails',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN -- no emails will be sent\n'))

        stats = send_close_check_emails(dry_run=dry_run)

        self.stdout.write(f"Eligible cycles: {stats['eligible']}")

        if not dry_run:
            self.stdout.write(f"Emails sent: {stats['sent']}")

        if stats['errors']:
            for error in stats['errors']:
                self.stderr.write(self.style.ERROR(f"  {error}"))

        if not stats['errors']:
            self.stdout.write(self.style.SUCCESS('Done.'))
