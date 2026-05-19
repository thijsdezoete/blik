import uuid
from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext, gettext_lazy as _
from django.utils.crypto import get_random_string
from core.models import TimeStampedModel, Organization
from core.managers import OrganizationManager


class UserProfile(TimeStampedModel):
    """Extended user profile with organization relationship"""
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name=_('user')
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='users',
        verbose_name=_('organization')
    )
    can_create_cycles_for_others = models.BooleanField(
        default=False,
        help_text=_('If False, user can only create cycles for themselves'),
        verbose_name=_('can create cycles for others')
    )
    has_seen_welcome = models.BooleanField(
        default=False,
        help_text=_('Whether user has seen the welcome modal'),
        verbose_name=_('has seen welcome')
    )
    language = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text=_('Language of the dashboard and of emails to this user. Empty: the browser language.'),
        verbose_name=_('language')
    )

    objects = OrganizationManager()

    class Meta:
        verbose_name = _('user profile')
        verbose_name_plural = _('user profiles')
        db_table = 'user_profiles'
        ordering = ['user__username']
        permissions = [
            ('can_invite_members', 'Can invite team members'),
            ('can_manage_organization', 'Can manage organization settings'),
            ('can_delete_organization', 'Can delete organization'),
            ('can_view_all_reports', 'Can view all organization reports'),
            ('can_manage_questionnaires', 'Can create and edit questionnaires'),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.organization.name}"


class OrganizationInvitation(TimeStampedModel):
    """Invitation to join an organization"""
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='invitations',
        verbose_name=_('organization')
    )
    email = models.EmailField(_('email'))
    token = models.CharField(_('token'), max_length=64, unique=True, db_index=True)
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_invitations',
        verbose_name=_('invited by')
    )
    accepted_at = models.DateTimeField(_('accepted at'), null=True, blank=True)
    expires_at = models.DateTimeField(_('expires at'))

    objects = OrganizationManager()

    class Meta:
        verbose_name = _('invitation')
        verbose_name_plural = _('invitations')
        db_table = 'organization_invitations'
        ordering = ['-created_at']
        unique_together = ['organization', 'email']

    def __str__(self):
        return gettext('Invite %(email)s to %(organization)s') % {'email': self.email, 'organization': self.organization.name}

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = get_random_string(64)
        super().save(*args, **kwargs)

    def is_valid(self):
        """Check if invitation is still valid"""
        from django.utils import timezone
        return (
            self.accepted_at is None and
            self.expires_at > timezone.now()
        )


class PasswordResetToken(TimeStampedModel):
    """Token for password reset requests"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_reset_tokens',
        verbose_name=_('user')
    )
    token = models.CharField(_('token'), max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(_('expires at'))
    used_at = models.DateTimeField(_('used at'), null=True, blank=True)

    class Meta:
        verbose_name = _('password reset token')
        verbose_name_plural = _('password reset tokens')
        db_table = 'password_reset_tokens'
        ordering = ['-created_at']

    def __str__(self):
        return gettext('Password reset for %(email)s') % {'email': self.user.email}

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = get_random_string(64)
        if not self.expires_at:
            from django.utils import timezone
            from datetime import timedelta
            self.expires_at = timezone.now() + timedelta(hours=1)
        super().save(*args, **kwargs)

    def is_valid(self):
        """Check if token is still valid (not expired and not used)"""
        from django.utils import timezone
        return self.used_at is None and self.expires_at > timezone.now()


class Reviewee(TimeStampedModel):
    """Person being reviewed in 360 feedback"""
    # Public UUID for external references (API, URLs)
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text=_('Public identifier for API and URL usage (non-enumerable)'),
        verbose_name=_('UUID')
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='reviewees',
        verbose_name=_('organization')
    )
    name = models.CharField(_('name'), max_length=255)
    email = models.EmailField(_('email'))
    department = models.CharField(_('department'), max_length=255, blank=True)
    language = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text=_("Language of emails to this person. Empty: the organization's default language."),
        verbose_name=_('language')
    )
    is_active = models.BooleanField(_('active'), default=True)

    objects = OrganizationManager()

    class Meta:
        verbose_name = _('reviewee')
        verbose_name_plural = _('reviewees')
        db_table = 'reviewees'
        ordering = ['name']
        unique_together = ['organization', 'email']

    def __str__(self):
        return f"{self.name} ({self.email})"


class Team(TimeStampedModel):
    """
    A team / pyramid in the org chart.

    Each team renders as a two-tier pyramid: a single "manager row" at the top
    (row 0) with `shape.manager_cols` slots, and one or more "member rows"
    below, each described by an entry in `shape.member_rows`.

    A person can be a member of multiple teams (and can simultaneously be a
    manager of some teams and a member of others). This is what lets the org
    chart capture "VP of Eng is a member of Leadership AND a manager of
    Engineering" — one person, two memberships across two teams.
    """
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='teams',
    )
    name = models.CharField(max_length=255)
    display_order = models.IntegerField(default=0)
    # Grid shape: {"manager_cols": 3, "member_rows": [{"cols": 3}, {"cols": 5}]}
    shape = models.JSONField(default=dict)

    objects = OrganizationManager()

    class Meta:
        db_table = 'teams'
        ordering = ['display_order', 'name']
        unique_together = ['organization', 'name']

    def __str__(self):
        return self.name

    def default_shape(self):
        """Minimal valid shape used when the stored one is empty."""
        return {'manager_cols': 1, 'member_rows': [{'cols': 3}]}

    def effective_shape(self):
        s = self.shape or {}
        if not s.get('manager_cols') or not s.get('member_rows'):
            return self.default_shape()
        return s

    def slot_fits(self, row, col):
        """Return True if (row, col) is a valid slot in this team's shape."""
        s = self.effective_shape()
        try:
            row = int(row)
            col = int(col)
        except (TypeError, ValueError):
            return False
        if row == 0:
            return 0 <= col < int(s['manager_cols'])
        member_rows = s.get('member_rows') or []
        member_idx = row - 1
        if 0 <= member_idx < len(member_rows):
            return 0 <= col < int(member_rows[member_idx].get('cols', 0))
        return False


class TeamMembership(TimeStampedModel):
    """
    Occupancy of a single slot in a team's pyramid.

    `role` is derived from `row` (row 0 = manager, row > 0 = member) but is
    stored denormalized so queries like "all teams where Alice is a manager"
    don't require expression indexes or per-row arithmetic.
    """
    MANAGER = 'manager'
    MEMBER = 'member'
    ROLE_CHOICES = [(MANAGER, 'Manager'), (MEMBER, 'Member')]

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    reviewee = models.ForeignKey(
        Reviewee,
        on_delete=models.CASCADE,
        related_name='team_memberships',
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    row = models.IntegerField()
    col = models.IntegerField()

    class Meta:
        db_table = 'team_memberships'
        ordering = ['team_id', 'row', 'col']
        unique_together = [
            ('team', 'reviewee'),   # one slot per person per team
            ('team', 'row', 'col'),  # one person per slot
        ]

    def __str__(self):
        return f'{self.reviewee.name} @ {self.team.name} r{self.row}c{self.col} ({self.role})'

    def save(self, *args, **kwargs):
        # Role is mechanically derived from row; enforce it here so the two
        # can't drift via direct DB updates.
        self.role = self.MANAGER if self.row == 0 else self.MEMBER
        super().save(*args, **kwargs)
