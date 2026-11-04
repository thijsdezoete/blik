"""
Send the emails that tell a customer their trial ends in 3 days, and in 1 day.

Designed to run daily via cron:
    python manage.py send_trial_reminders

Each reminder goes out once per subscription, so a second run on the same day sends nothing.

Usage:
    python manage.py send_trial_reminders            # Send emails
    python manage.py send_trial_reminders --dry-run   # Preview without sending
"""
from django.core.management.base import BaseCommand

from notifications.log import record_run
from subscriptions.emails import send_trial_reminders


class Command(BaseCommand):
    help = 'Send trial-ending reminders 3 days and 1 day before a trial ends'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show how many reminders are due without sending emails',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN -- no emails will be sent\n'))

        stats = send_trial_reminders(dry_run=dry_run)

        self.stdout.write(f"Reminders due: {stats['eligible']}")

        if not dry_run:
            record_run('send_trial_reminders', stats['sent'], stats['errors'])
            self.stdout.write(f"Reminders sent: {stats['sent']}")

        for error in stats['errors']:
            self.stderr.write(self.style.ERROR(f"  {error}"))

        if not stats['errors']:
            self.stdout.write(self.style.SUCCESS('Done.'))
