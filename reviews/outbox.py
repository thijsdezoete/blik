"""The email outbox for invitations, reminders and the reviewee's links to share.

An admin's "send" only puts the email in the queue: a timestamp on the reviewer token, or on
the cycle for the reviewee's links email. The send_queued_invitations cron drains the queue
every five minutes. A slow mail relay never holds up a web request, and a crash costs at
most the one email that was being sent.

The cron sends one email per address. A person who reviews several colleagues, or one
colleague on several questionnaires, gets one email with every link. Each address is its
own transaction: the tokens are locked, the email goes out, the tokens are marked sent.
A failure is recorded on the tokens for the admin to see and tried again on later runs.
"""
import logging

from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext as _

from core.email import get_email_backend
from .models import ReviewCycle, ReviewerToken
from .services import self_assessment_token, send_bundle_email, send_links_email, send_token_email

logger = logging.getLogger('reviews.outbox')

# After this many failed attempts the email stays in the queue as failed until an admin
# sends it again; so a mail server that is down does not get a knock every five minutes forever.
MAX_ATTEMPTS = 5

INVITATION = 'invitation'
REMINDER = 'reminder'

# Which fields each kind of queued email lives in on the token
QUEUED_AT = {INVITATION: 'invitation_queued_at', REMINDER: 'reminder_queued_at'}
SENT_AT = {INVITATION: 'invitation_sent_at', REMINDER: 'last_reminder_sent_at'}


def addressed(tokens):
    """Only the tokens with an address."""
    return tokens.filter(reviewer_email__isnull=False).exclude(reviewer_email='')


def queue_invitations(tokens):
    """Put the pending invitations among `tokens` in the outbox. Returns how many.

    Pending: addressed, not sent, not completed. Queued again, a failed one gets a fresh set
    of attempts.
    """
    pending = addressed(tokens).filter(invitation_sent_at__isnull=True, completed_at__isnull=True)
    return pending.update(invitation_queued_at=timezone.now(), email_error='', email_attempts=0)


def queue_reminders(tokens):
    """Put a reminder for every invited, unfinished token among `tokens` in the outbox. Returns how many."""
    due = addressed(tokens).filter(invitation_sent_at__isnull=False, completed_at__isnull=True)
    return due.update(reminder_queued_at=timezone.now(), email_error='', email_attempts=0)


def queue_reviewee_notifications(cycle):
    """Queue the emails a reviewee gets when their cycle starts.

    The self-assessment, when the cycle collects one: it is a token like any other, so a
    reviewee who also reviews colleagues gets it in the same bundle. And the links to share,
    when the cycle collects feedback from others. A reviewee without an address gets nothing.

    Returns the number of emails queued.
    """
    if not cycle.reviewee.email:
        return 0

    queued = 0
    if cycle.collects('self'):
        queued += queue_invitations(ReviewerToken.objects.filter(pk=self_assessment_token(cycle).pk))

    if any(category != 'self' for category in cycle.active_categories):
        cycle.links_email_queued_at = timezone.now()
        cycle.links_email_error = ''
        cycle.links_email_attempts = 0
        cycle.save(update_fields=['links_email_queued_at', 'links_email_error', 'links_email_attempts'])
        queued += 1

    return queued


def queued_tokens(kind):
    """The tokens with a queued email of this kind that the cron still has to send."""
    return ReviewerToken.objects.filter(
        **{f'{QUEUED_AT[kind]}__isnull': False},
        cycle__status='active',
        completed_at__isnull=True,
        email_attempts__lt=MAX_ATTEMPTS,
    )


def queued_links_emails():
    """The cycles whose links email the cron still has to send."""
    return ReviewCycle.objects.filter(
        links_email_queued_at__isnull=False,
        status='active',
        links_email_attempts__lt=MAX_ATTEMPTS,
    )


def drop_stale():
    """Take back what must not go out any more: emails for cycles that are no longer active,
    and invitations and reminders for reviews that are finished."""
    ReviewerToken.objects.filter(
        Q(invitation_queued_at__isnull=False) | Q(reminder_queued_at__isnull=False),
    ).filter(
        Q(completed_at__isnull=False) | ~Q(cycle__status='active'),
    ).update(invitation_queued_at=None, reminder_queued_at=None, email_error='', email_attempts=0)

    ReviewCycle.objects.filter(links_email_queued_at__isnull=False).exclude(status='active').update(
        links_email_queued_at=None, links_email_error='', links_email_attempts=0,
    )


def error_text(error):
    """What the admin reads about a failed send."""
    return f'{type(error).__name__}: {error}' if str(error) else type(error).__name__


def record_failure(queryset, error, prefix):
    """Note the failure on the queued rows, one attempt closer to the cap."""
    queryset.update(**{
        f'{prefix}error': error_text(error),
        f'{prefix}attempts': F(f'{prefix}attempts') + 1,
    })


def close_quietly(connection):
    """Drop the connection; a broken one must not stop the next email from opening a new one."""
    try:
        connection.close()
    except Exception:
        logger.exception('Closing the email connection failed')


def send_queued_emails():
    """Send everything in the outbox, one email per address. The cron's job.

    Returns {'sent': emails sent, 'tokens': tokens they covered, 'errors': [...]}.
    """
    stats = {'sent': 0, 'tokens': 0, 'errors': []}
    drop_stale()

    if not (queued_tokens(INVITATION).exists() or queued_tokens(REMINDER).exists() or queued_links_emails().exists()):
        return stats

    # One connection for the whole run: opening one per email is what made a bulk send slow
    connection = get_email_backend()
    try:
        connection.open()
    except Exception as e:
        logger.exception('Opening the email connection failed')
        for queryset, prefix in (
            (queued_tokens(INVITATION), 'email_'),
            (queued_tokens(REMINDER), 'email_'),
            (queued_links_emails(), 'links_email_'),
        ):
            record_failure(queryset, e, prefix)
        stats['errors'].append(_('Could not connect to the mail server: %(error)s') % {'error': error_text(e)})
        return stats

    try:
        for kind in (INVITATION, REMINDER):
            for organization_id, email in queued_addresses(kind):
                send_to_address(kind, organization_id, email, connection, stats)

        for cycle_id in list(queued_links_emails().order_by('pk').values_list('pk', flat=True)):
            send_queued_links_email(cycle_id, connection, stats)
    finally:
        close_quietly(connection)

    return stats


def queued_addresses(kind):
    """(organization id, lowercased address) for every queued email of this kind, each once."""
    return list(
        queued_tokens(kind)
        .annotate(address=Lower('reviewer_email'))
        .order_by('cycle__reviewee__organization_id', 'address')
        .values_list('cycle__reviewee__organization_id', 'address')
        .distinct()
    )


def send_to_address(kind, organization_id, email, connection, stats):
    """One email to one address with every queued form, in its own transaction."""
    with transaction.atomic():
        # Locked until the send is recorded, so a second run skips them meanwhile
        tokens = list(
            queued_tokens(kind)
            .filter(cycle__reviewee__organization_id=organization_id, reviewer_email__iexact=email)
            .select_for_update(skip_locked=True, of=('self',))
            .select_related('cycle__reviewee__organization', 'cycle__questionnaire')
            .order_by('pk')
        )
        if not tokens:
            return

        try:
            if len(tokens) == 1:
                send_token_email(tokens[0], reminder=kind == REMINDER, connection=connection)
            else:
                send_bundle_email(email, tokens, reminder=kind == REMINDER, connection=connection)
        except Exception as e:
            logger.exception('Sending the %s email to %s failed', kind, email)
            record_failure(ReviewerToken.objects.filter(pk__in=[t.pk for t in tokens]), e, 'email_')
            stats['errors'].append(_('Failed to send to %(email)s: %(error)s') % {'email': email, 'error': error_text(e)})
            close_quietly(connection)
            return

        ReviewerToken.objects.filter(pk__in=[t.pk for t in tokens]).update(**{
            SENT_AT[kind]: timezone.now(),
            QUEUED_AT[kind]: None,
            'email_error': '',
            'email_attempts': 0,
        })
        stats['sent'] += 1
        stats['tokens'] += len(tokens)


def send_queued_links_email(cycle_id, connection, stats):
    """The reviewee's links to share for one cycle, in its own transaction."""
    with transaction.atomic():
        cycle = (
            queued_links_emails()
            .filter(pk=cycle_id)
            .select_for_update(skip_locked=True, of=('self',))
            .select_related('reviewee__organization', 'questionnaire')
            .first()
        )
        if cycle is None:
            return

        categories = [category for category in cycle.active_categories if category != 'self']
        try:
            send_links_email(cycle, categories, connection=connection)
        except Exception as e:
            logger.exception('Sending the links email for cycle %s failed', cycle_id)
            record_failure(ReviewCycle.objects.filter(pk=cycle.pk), e, 'links_email_')
            stats['errors'].append(
                _('Failed to send the links to %(email)s: %(error)s') % {'email': cycle.reviewee.email, 'error': error_text(e)}
            )
            close_quietly(connection)
            return

        ReviewCycle.objects.filter(pk=cycle.pk).update(
            links_email_queued_at=None, links_email_error='', links_email_attempts=0,
        )
        stats['sent'] += 1
