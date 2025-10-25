"""
Signal handlers for user registration
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from core.models import Organization
from core.email import send_welcome_email
from .models import UserProfile

User = get_user_model()


# NOTE: Allauth signals removed - registration now only via Stripe or invitations
# User profile creation happens in:
# 1. Stripe webhook (subscriptions/views.py) - primary registration path
# 2. Invitation acceptance (accounts/invitation_views.py) - team member invites


@receiver(post_save, sender=UserProfile)
def create_reviewee_from_user(sender, instance, created, **kwargs):
    """
    Auto-create a reviewee when a user profile is created.
    This ensures team members show up in the reviewee list automatically.
    """
    if created:
        from accounts.models import Reviewee

        # Check if reviewee already exists with this email
        existing = Reviewee.objects.filter(
            organization=instance.organization,
            email=instance.user.email
        ).first()

        if not existing:
            # Create reviewee from user
            name = instance.user.get_full_name() or instance.user.username
            Reviewee.objects.create(
                organization=instance.organization,
                name=name,
                email=instance.user.email,
                is_active=True
            )


