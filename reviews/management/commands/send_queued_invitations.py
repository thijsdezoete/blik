"""
Send the invitation, reminder and links-to-share emails that admins queued, one email per address.

An admin's "send" only queues; this drains the queue. Runs every 5 minutes via cron:
    python manage.py send_queued_invitations
"""
from django.core.management.base import BaseCommand

from notifications.log import record_run
from reviews.outbox import send_queued_emails


class Command(BaseCommand):
    help = 'Send the queued invitation and reminder emails, one email per address'

    def handle(self, *args, **options):
        stats = send_queued_emails()

        if stats['sent'] or stats['errors']:
            # Every 5 minutes: record only runs that did something, so the cron log stays readable
            record_run('send_queued_invitations', stats['sent'], stats['errors'])
            self.stdout.write(f"Emails sent: {stats['sent']} (covering {stats['tokens']} reviewer tokens)")

        for error in stats['errors']:
            self.stderr.write(self.style.ERROR(f'  {error}'))
