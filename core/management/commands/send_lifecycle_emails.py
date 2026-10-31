"""
Send the lifecycle emails that are due today: onboarding nudges, the next-cycle reminder and the
report follow-up. Each email goes out once, so running twice a day sends nothing new.

Designed to run daily via cron:
    python manage.py send_lifecycle_emails

Usage:
    python manage.py send_lifecycle_emails            # Send emails
    python manage.py send_lifecycle_emails --dry-run  # Preview without sending
"""
from django.core.management.base import BaseCommand

from notifications import lifecycle
from notifications.log import record_run


# (label, selector, sender). A selector returns the objects due today; sender(*object) sends one email.
EMAILS = [
    ('No review cycle yet', lifecycle.organizations_without_cycle, lifecycle.send_no_cycle_nudge),
    ('No reviewers yet', lifecycle.organizations_without_reviewers, lifecycle.send_no_reviewers_nudge),
    ('Next cycle reminder', lifecycle.organizations_due_next_cycle, lifecycle.send_next_cycle_reminder),
    ('Report follow-up', lifecycle.reports_due_follow_up, lifecycle.send_report_follow_up),
]


class Command(BaseCommand):
    help = 'Send onboarding nudges, next-cycle reminders and report follow-ups that are due'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show how many emails are due without sending them',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN -- no emails will be sent\n'))

        errors = []
        total_sent = 0
        for label, select, send in EMAILS:
            due = select()
            sent = 0
            if not dry_run:
                for item in due:
                    args = item if isinstance(item, tuple) else (item,)
                    try:
                        sent += send(*args)
                    except Exception as e:
                        errors.append(f'{label} for {args[0]!r}: {e}')

            total_sent += sent
            self.stdout.write(f'{label}: {len(due)} due' + ('' if dry_run else f', {sent} sent'))

        if not dry_run:
            record_run('send_lifecycle_emails', total_sent, errors)

        for error in errors:
            self.stderr.write(self.style.ERROR(f'  {error}'))

        if not errors:
            self.stdout.write(self.style.SUCCESS('Done.'))
