"""The email log and the cron run log that the operator reads in the Django admin."""
from core.email import send_email

from .models import CronRun, EmailLog


def send_logged(organization, kind, **email):
    """send_email(**email), and record it in the email log. Only for emails to customers, never to reviewers."""
    entry = EmailLog(organization=organization, kind=kind, recipient=email['recipient_list'][0])
    try:
        sent = send_email(**email)
    except Exception as e:
        entry.error = str(e)
        entry.save()
        raise
    if not sent:
        entry.error = 'Not sent'
    entry.save()
    return sent


def record_run(command, sent, errors):
    """
    Record one run of a cron email command. The daily commands record every run, also those that tried nothing,
    so the last one shows cron runs. finalize_reports runs every 5 minutes and records only runs that did something.
    """
    # ponytail: a few small rows a day (the daily commands, plus finalize_reports runs that did something),
    # never pruned; add a cleanup when the table matters
    return CronRun.objects.create(command=command, sent=sent, errors='\n'.join(errors))
