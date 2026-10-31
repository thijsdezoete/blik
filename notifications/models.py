from django.db import models
from django.utils.translation import gettext_lazy as _


class SentEmail(models.Model):
    """An email that went out about one object, so that it goes out only once.

    The kind says which model object_id belongs to: an organization, a review cycle or a report.
    Never a reviewer token: that would link reviewers to what they reviewed.
    """

    NO_CYCLE = 'no_cycle'                            # organization
    NO_REVIEWERS = 'no_reviewers'                    # organization
    FEEDBACK_CONVERSATION = 'feedback_conversation'  # organization
    CYCLE_SUMMARY = 'cycle_summary'                  # review cycle
    NEXT_CYCLE = 'next_cycle'                        # review cycle, the organization's last closed one
    REPORT_READY = 'report_ready'                    # report
    REPORT_FOLLOW_UP = 'report_follow_up'            # report

    KIND_CHOICES = [
        (NO_CYCLE, _('No review cycle yet')),
        (NO_REVIEWERS, _('No reviewers yet')),
        (FEEDBACK_CONVERSATION, _('How to run the feedback conversation')),
        (CYCLE_SUMMARY, _('Cycle summary')),
        (NEXT_CYCLE, _('Next cycle reminder')),
        (REPORT_READY, _('Report ready')),
        (REPORT_FOLLOW_UP, _('Report follow-up')),
    ]

    kind = models.CharField(_('kind'), max_length=40, choices=KIND_CHOICES)
    object_id = models.PositiveBigIntegerField(_('object id'))
    sent_at = models.DateTimeField(_('sent at'), auto_now_add=True)

    class Meta:
        verbose_name = _('sent email')
        verbose_name_plural = _('sent emails')
        db_table = 'sent_emails'
        constraints = [
            models.UniqueConstraint(fields=['kind', 'object_id'], name='sent_email_once_per_object'),
        ]

    def __str__(self):
        return f'{self.kind} {self.object_id}'


class EmailLog(models.Model):
    """One email to a customer: an organization's admins or reviewees. Never to a reviewer.

    Only for looking up what went out. SentEmail is what makes an email go out once.
    """

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='email_log', verbose_name=_('organization'),
    )
    kind = models.CharField(_('kind'), max_length=60)
    recipient = models.EmailField(_('recipient'))
    sent_at = models.DateTimeField(_('sent at'), auto_now_add=True)
    error = models.TextField(_('error'), blank=True)

    class Meta:
        verbose_name = _('email log entry')
        verbose_name_plural = _('email log')
        db_table = 'email_log'
        ordering = ['-sent_at']

    def __str__(self):
        return f'{self.kind} to {self.recipient}'


class CronRun(models.Model):
    """One run of a daily email command."""

    command = models.CharField(_('command'), max_length=60)
    ran_at = models.DateTimeField(_('ran at'), auto_now_add=True)
    sent = models.PositiveIntegerField(_('sent'), default=0)
    errors = models.TextField(_('errors'), blank=True)

    class Meta:
        verbose_name = _('cron run')
        verbose_name_plural = _('cron runs')
        db_table = 'cron_runs'
        ordering = ['-ran_at']

    def __str__(self):
        return f'{self.command} {self.ran_at:%Y-%m-%d %H:%M}'
