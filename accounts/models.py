from django.contrib.auth.models import User
from django.db import models
from core.models import TimeStampedModel, Organization


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

    class Meta:
        db_table = 'user_profiles'
        ordering = ['user__username']

    def __str__(self):
        return f"{self.user.username} - {self.organization.name}"


class Reviewee(TimeStampedModel):
    """Person being reviewed in 360 feedback"""
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='reviewees'
    )
    name = models.CharField(max_length=255)
    email = models.EmailField()
    department = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'reviewees'
        ordering = ['name']
        unique_together = ['organization', 'email']

    def __str__(self):
        return f"{self.name} ({self.email})"
