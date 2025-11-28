import uuid
from django.contrib.auth.models import User
from django.db import models
from django.utils.crypto import get_random_string
from core.models import TimeStampedModel, Organization
from core.managers import OrganizationManager


class UserProfile(TimeStampedModel):
    """Extended user profile with organization relationship"""
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='users'
    )
    can_create_cycles_for_others = models.BooleanField(
        default=False,
        help_text='If False, user can only create cycles for themselves'
    )
    has_seen_welcome = models.BooleanField(
        default=False,
        help_text='Whether user has seen the welcome modal'
    )

    objects = OrganizationManager()

    class Meta:
        db_table = 'user_profiles'
        ordering = ['user__username']
        permissions = [
            ('can_invite_members', 'Can invite team members'),
            ('can_manage_organization', 'Can manage organization settings'),
            ('can_delete_organization', 'Can delete organization'),
            ('can_view_all_reports', 'Can view all organization reports'),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.organization.name}"


class OrganizationInvitation(TimeStampedModel):
    """Invitation to join an organization"""
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='invitations'
    )
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, db_index=True)
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_invitations'
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    objects = OrganizationManager()

    class Meta:
        db_table = 'organization_invitations'
        ordering = ['-created_at']
        unique_together = ['organization', 'email']

    def __str__(self):
        return f"Invite {self.email} to {self.organization.name}"

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
        related_name='password_reset_tokens'
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'password_reset_tokens'
        ordering = ['-created_at']

    def __str__(self):
        return f"Password reset for {self.user.email}"

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
        help_text="Public identifier for API and URL usage (non-enumerable)"
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='reviewees'
    )
    name = models.CharField(max_length=255)
    email = models.EmailField()
    department = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'reviewees'
        ordering = ['name']
        unique_together = ['organization', 'email']

    def __str__(self):
        return f"{self.name} ({self.email})"
