import uuid
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from core.models import TimeStampedModel
from core.managers import ReviewCycleManager, ReviewerTokenManager, ResponseManager
from accounts.models import Reviewee
from questionnaires.models import Questionnaire, Question


# The order feedback categories are collected, displayed and reported in.
# Single source for the places that used to spell the list out themselves.
CATEGORY_ORDER = ('self', 'peer', 'manager', 'direct_report')


class ReviewCycle(TimeStampedModel):
    """360 feedback review cycle for a reviewee"""

    STATUS_CHOICES = [
        ('active', _('Active')),
        ('completed', _('Completed')),
    ]

    # Public UUID for external references (API, URLs)
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text=_('Public identifier for API and URL usage (non-enumerable)'),
        verbose_name=_('UUID')
    )

    reviewee = models.ForeignKey(
        Reviewee,
        on_delete=models.CASCADE,
        related_name='review_cycles',
        verbose_name=_('reviewee')
    )
    questionnaire = models.ForeignKey(
        Questionnaire,
        on_delete=models.PROTECT,
        related_name='review_cycles',
        verbose_name=_('questionnaire')
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_review_cycles',
        verbose_name=_('created by')
    )
    status = models.CharField(_('status'), max_length=20, choices=STATUS_CHOICES, default='active')
    close_check_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When the close check-in email was sent to the reviewee'),
        verbose_name=_('close check sent at')
    )

    report_finalized_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When the cycle was finalised and its report emailed'),
        verbose_name=_('report finalized at')
    )

    # The outbox for the reviewee's "links to share" email, sent by the send_queued_invitations
    # cron like the reviewer invitations. It is the one email that belongs to the cycle, not to
    # a token: a cycle without a self-assessment has no token addressed to the reviewee.
    links_email_queued_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When the links-to-share email to the reviewee was put in the outbox. Empty once it is sent.'),
        verbose_name=_('links email queued at')
    )
    links_email_error = models.TextField(
        blank=True,
        default='',
        help_text=_('Why the last attempt to send the links-to-share email failed'),
        verbose_name=_('links email error')
    )
    links_email_attempts = models.PositiveSmallIntegerField(
        default=0,
        help_text=_('Failed attempts to send the links-to-share email'),
        verbose_name=_('links email attempts')
    )

    @property
    def organization(self):
        """Get organization through reviewee relationship"""
        return self.reviewee.organization

    # Which categories this cycle collects feedback for. All four by default,
    # which is what every cycle did before these flags existed.
    include_self = models.BooleanField(_('Self assessment'), default=True)
    include_peer = models.BooleanField(_('Peer review'), default=True)
    include_manager = models.BooleanField(_('Manager review'), default=True)
    include_direct_report = models.BooleanField(_('Direct report review'), default=True)

    # Secure invitation tokens per category (non-enumerable)
    invitation_token_self = models.UUIDField(_('self assessment invitation token'), unique=True, db_index=True, null=True, blank=True)
    invitation_token_peer = models.UUIDField(_('peer review invitation token'), unique=True, db_index=True, null=True, blank=True)
    invitation_token_manager = models.UUIDField(_('manager review invitation token'), unique=True, db_index=True, null=True, blank=True)
    invitation_token_direct_report = models.UUIDField(_('direct report review invitation token'), unique=True, db_index=True, null=True, blank=True)

    objects = ReviewCycleManager()

    class Meta:
        verbose_name = _('review cycle')
        verbose_name_plural = _('review cycles')
        db_table = 'review_cycles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reviewee.name} - {self.created_at.strftime('%Y-%m-%d')}"

    def save(self, *args, **kwargs):
        """On creation: generate invitation tokens and pay for the cycle."""
        if self.pk:
            super().save(*args, **kwargs)
            return

        if not self.invitation_token_self:
            self.invitation_token_self = uuid.uuid4()
        if not self.invitation_token_peer:
            self.invitation_token_peer = uuid.uuid4()
        if not self.invitation_token_manager:
            self.invitation_token_manager = uuid.uuid4()
        if not self.invitation_token_direct_report:
            self.invitation_token_direct_report = uuid.uuid4()

        # Every creation path goes through here, so this is the only place the
        # single-round credit is charged. One transaction: a failed insert
        # gives the credit back. Imported lazily; subscriptions imports accounts.
        from subscriptions.utils import consume_cycle_credits
        with transaction.atomic():
            consume_cycle_credits(self.reviewee.organization)
            super().save(*args, **kwargs)

    @property
    def active_categories(self):
        """The categories this cycle collects, in report order."""
        return [c for c in CATEGORY_ORDER if getattr(self, f'include_{c}')]

    def collects(self, category):
        """Whether this cycle collects feedback for a category."""
        return category in self.active_categories

    def get_invitation_token(self, category):
        """Get the invitation token for a specific category"""
        token_map = {
            'self': self.invitation_token_self,
            'peer': self.invitation_token_peer,
            'manager': self.invitation_token_manager,
            'direct_report': self.invitation_token_direct_report,
        }
        return token_map.get(category)


# After this many failed attempts the outbox cron gives up on a queued email; an admin sends it again.
MAX_EMAIL_ATTEMPTS = 5


class ReviewerToken(TimeStampedModel):
    """Anonymous token for reviewer access"""

    CATEGORY_CHOICES = [
        ('self', _('Self Assessment')),
        ('peer', _('Peer Review')),
        ('manager', _('Manager Review')),
        ('direct_report', _('Direct Report Review')),
    ]

    cycle = models.ForeignKey(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name='tokens',
        verbose_name=_('review cycle')
    )
    token = models.UUIDField(_('token'), default=uuid.uuid4, unique=True, editable=False, db_index=True)
    category = models.CharField(_('feedback category'), max_length=20, choices=CATEGORY_CHOICES)
    reviewer_email = models.EmailField(
        null=True,
        blank=True,
        help_text=_('Email to send invitation to (not stored with responses for anonymity)'),
        verbose_name=_('reviewer email')
    )
    invitation_sent_at = models.DateTimeField(_('invitation sent at'), null=True, blank=True)
    last_reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When the last reminder email was sent to this reviewer'),
        verbose_name=_('last reminder sent at')
    )
    # The outbox. An admin's "send" puts an email in the queue; the send_queued_invitations
    # cron sends it and clears the queued_at. Only one of the two can be queued: a reminder
    # needs a sent invitation. The error and the attempts belong to whichever is queued.
    invitation_queued_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When the invitation was put in the outbox. Empty once it is sent.'),
        verbose_name=_('invitation queued at')
    )
    reminder_queued_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When a reminder was put in the outbox. Empty once it is sent.'),
        verbose_name=_('reminder queued at')
    )
    email_error = models.TextField(
        blank=True,
        default='',
        help_text=_('Why the last attempt to send the queued email failed'),
        verbose_name=_('email error')
    )
    email_attempts = models.PositiveSmallIntegerField(
        default=0,
        help_text=_('Failed attempts to send the queued email'),
        verbose_name=_('email attempts')
    )
    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('When someone claimed this token by clicking the invitation link'),
        verbose_name=_('claimed at')
    )
    completed_at = models.DateTimeField(_('completed at'), null=True, blank=True)
    language = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text=_('Language of the form and of emails to this reviewer. Empty until the form is first opened.'),
        verbose_name=_('language')
    )

    objects = ReviewerTokenManager()

    class Meta:
        verbose_name = _('reviewer token')
        verbose_name_plural = _('reviewer tokens')
        db_table = 'reviewer_tokens'
        ordering = ['cycle', 'category']

    def __str__(self):
        return f"{self.cycle} - {self.get_category_display()}"

    def save(self, *args, **kwargs):
        """On creation of a reviewer token: keep a free organization's cycle within its reviewer cap."""
        if not self._state.adding:
            super().save(*args, **kwargs)
            return

        # Every creation path goes through here, like the cycle-credit gate. The lock on the
        # cycle row makes concurrent additions count one after another. Only tokens per cycle
        # are counted; nothing links a reviewer to their answers. The cycle's one
        # self-assessment is free; any further self token counts as a reviewer.
        from subscriptions.utils import FREE_REVIEWERS_PER_CYCLE, ReviewerLimit, is_free_tier
        with transaction.atomic():
            list(ReviewCycle._base_manager.select_for_update().filter(pk=self.cycle_id).values_list('pk'))
            if is_free_tier(self.cycle.reviewee.organization):
                tokens = ReviewerToken._base_manager.filter(cycle_id=self.cycle_id)
                has_self = tokens.filter(category='self').exists()
                is_first_self = self.category == 'self' and not has_self
                reviewers = tokens.count() - (1 if has_self else 0)
                if not is_first_self and reviewers >= FREE_REVIEWERS_PER_CYCLE:
                    raise ReviewerLimit()
            super().save(*args, **kwargs)

    @property
    def is_completed(self):
        return self.completed_at is not None

    @property
    def email_gave_up(self):
        """The queued email failed on every attempt: the cron stopped trying, an admin has to send it again."""
        return bool(self.email_error) and self.email_attempts >= MAX_EMAIL_ATTEMPTS


class Response(TimeStampedModel):
    """Individual response to a question"""

    cycle = models.ForeignKey(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name='responses',
        verbose_name=_('review cycle')
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='responses',
        verbose_name=_('question')
    )
    token = models.ForeignKey(
        ReviewerToken,
        on_delete=models.CASCADE,
        related_name='responses',
        verbose_name=_('reviewer token')
    )
    category = models.CharField(_('feedback category'), max_length=20)  # Denormalized from token for reporting

    # JSON field for storing answer data
    # For rating: {"value": 4}
    # For scale: {"value": 75}
    # For text: {"value": "text response"}
    # For single_choice: {"value": "Option 1"}
    # For multiple_choice: {"value": ["Option 1", "Option 2"]}
    answer_data = models.JSONField(_('answer data'))

    objects = ResponseManager()

    class Meta:
        verbose_name = _('response')
        verbose_name_plural = _('responses')
        db_table = 'responses'
        ordering = ['cycle', 'question']
        unique_together = ['token', 'question']

    def __str__(self):
        return f'{self.cycle} - {self.question.short_text}'
