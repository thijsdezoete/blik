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


# Removed - no longer using allauth
# @receiver(user_signed_up)
def _old_create_user_profile_on_signup(sender, request, user, **kwargs):
    """
    Create UserProfile when user signs up

    Organization assignment logic:

    When ENABLE_MULTITENANCY=False (default):
    - Stripe webhook creates org + user + profile automatically
    - This signal should NOT be triggered for normal registration
    - Only handle invitation-based signups or manual admin creation

    When ENABLE_MULTITENANCY=True:
    1. Check invitation token (primary method)
    2. Check subdomain organization (from session)
    3. If exactly ONE org allows registration, use that
    4. Otherwise, raise error
    """
    from django.conf import settings

    # Check if profile already exists (e.g., created by Stripe webhook)
    if hasattr(user, 'profile'):
        return

    org = None

    # Priority 1: Organization from invitation token (works in both modes)
    if request and hasattr(request, 'session'):
        invitation_token = request.session.get('invitation_token')
        if invitation_token:
            from accounts.models import OrganizationInvitation
            try:
                invitation = OrganizationInvitation.objects.get(token=invitation_token)
                if invitation.is_valid() and invitation.email.lower() == user.email.lower():
                    org = invitation.organization
                    # Mark invitation as accepted
                    from django.utils import timezone
                    invitation.accepted_at = timezone.now()
                    invitation.save()
                    # Clear invitation from session
                    del request.session['invitation_token']
            except OrganizationInvitation.DoesNotExist:
                pass

    # If multitenancy is disabled and no invitation, this is a problem
    # Registration should only happen via Stripe or invitations
    if not settings.ENABLE_MULTITENANCY and not org:
        raise ValueError(
            f"User {user.email} registered without Stripe or invitation. "
            "In single-tenant mode, users must be created via Stripe checkout or invitation."
        )

    # Priority 2: Organization from subdomain (multitenancy mode only)
    if not org and settings.ENABLE_MULTITENANCY and request and hasattr(request, 'session'):
        org_id = request.session.get('current_organization_id')
        if org_id:
            try:
                org = Organization.objects.get(id=org_id, allow_registration=True, is_active=True)
            except Organization.DoesNotExist:
                pass

    # Priority 3: Single org with registration enabled (multitenancy mode only)
    if not org and settings.ENABLE_MULTITENANCY:
        orgs_with_registration = Organization.objects.filter(
            allow_registration=True,
            is_active=True
        )

        count = orgs_with_registration.count()

        if count == 1:
            org = orgs_with_registration.first()
        elif count == 0:
            raise ValueError(
                f"User {user.email} registered but no organizations allow registration. "
                "Enable registration in admin settings or use invitation system."
            )
        else:
            raise ValueError(
                f"User {user.email} registered but multiple organizations allow registration. "
                "Use subdomain or invitation-based registration."
            )

    # Create user profile
    if org:
        UserProfile.objects.create(
            user=user,
            organization=org,
            can_create_cycles_for_others=org.default_users_can_create_cycles
        )

        # Send welcome email
        try:
            send_welcome_email(user, org)
        except Exception as e:
            print(f"Failed to send welcome email to {user.email}: {e}")


# Removed - no longer using allauth
# @receiver(social_account_added)
def _old_link_social_account(sender, request, sociallogin, **kwargs):
    """
    Handle when a social account is linked to existing user
    """
    user = sociallogin.user

    # Ensure user has a profile
    if not hasattr(user, 'profile'):
        org = Organization.objects.filter(is_active=True).first()
        if org:
            UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'organization': org,
                    'can_create_cycles_for_others': org.default_users_can_create_cycles
                }
            )
