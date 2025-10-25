"""
Signal handlers for user registration
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from allauth.account.signals import user_signed_up
from allauth.socialaccount.signals import social_account_added
from core.models import Organization
from core.email import send_welcome_email
from .models import UserProfile

User = get_user_model()


@receiver(user_signed_up)
def create_user_profile_on_signup(sender, request, user, **kwargs):
    """
    Create UserProfile when user signs up

    Organization assignment logic:
    1. Check session for 'signup_organization_id' (set by registration view)
    2. If exactly ONE organization allows registration, use that
    3. Otherwise, raise error - multitenancy requires explicit org selection
    """
    # Check if profile already exists
    if hasattr(user, 'profile'):
        return

    org = None

    # Try to get organization from session (if we implement org selection)
    if request and hasattr(request, 'session'):
        org_id = request.session.get('signup_organization_id')
        if org_id:
            try:
                org = Organization.objects.get(id=org_id, allow_registration=True, is_active=True)
            except Organization.DoesNotExist:
                pass

    # If no org from session, check if there's exactly ONE org with registration enabled
    if not org:
        orgs_with_registration = Organization.objects.filter(
            allow_registration=True,
            is_active=True
        )

        count = orgs_with_registration.count()

        if count == 1:
            # Only one org allows registration - use it
            org = orgs_with_registration.first()
        elif count == 0:
            # No organizations allow registration
            raise ValueError(
                f"User {user.email} registered but no organizations allow registration. "
                "Enable registration in admin settings."
            )
        else:
            # Multiple orgs allow registration - need to implement org selection
            raise ValueError(
                f"User {user.email} registered but multiple organizations allow registration. "
                "Organization selection must be implemented (subdomain, path, or invite-based)."
            )

    # Create user profile
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


@receiver(social_account_added)
def link_social_account(sender, request, sociallogin, **kwargs):
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
