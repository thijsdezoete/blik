"""
Superuser-only views for administrative tasks
"""
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.models import User
from django.db import transaction

from core.models import Organization
from accounts.models import OrganizationInvitation, UserProfile
from core.email import send_email


def superuser_required(user):
    """Check if user is a superuser"""
    return user.is_superuser


@login_required
@user_passes_test(superuser_required)
def create_organization(request):
    """
    Superuser-only page to create organizations without payment plans.

    Creates the organization and sends an invitation to the specified admin email.
    The invited admin goes through the normal invitation acceptance flow.
    """
    if request.method == 'POST':
        org_name = request.POST.get('org_name', '').strip()
        admin_email = request.POST.get('admin_email', '').strip().lower()

        # Validation
        if not org_name:
            messages.error(request, 'Organization name is required.')
            return render(request, 'superuser/create_organization.html')

        if not admin_email:
            messages.error(request, 'Admin email is required.')
            return render(request, 'superuser/create_organization.html')

        # Check if organization with this name already exists
        if Organization.objects.filter(name=org_name).exists():
            messages.error(request, f'Organization "{org_name}" already exists.')
            return render(request, 'superuser/create_organization.html')

        # Check if user with this email already exists
        existing_user = User.objects.filter(email=admin_email).first()
        if existing_user:
            # Check if user already has a profile/organization
            if hasattr(existing_user, 'profile') and existing_user.profile.organization:
                messages.error(
                    request,
                    f'User with email {admin_email} already belongs to organization: {existing_user.profile.organization.name}'
                )
                return render(request, 'superuser/create_organization.html')

        try:
            with transaction.atomic():
                # Create organization
                org = Organization.objects.create(
                    name=org_name,
                    email=admin_email,
                    is_active=True,
                    allow_registration=False,
                    default_users_can_create_cycles=False
                )

                # Create invitation
                invitation = OrganizationInvitation.objects.create(
                    organization=org,
                    email=admin_email,
                    invited_by=request.user,
                    expires_at=timezone.now() + timedelta(days=7)
                )

                # Build invitation URL
                invite_url = request.build_absolute_uri(
                    reverse('accept_invitation', kwargs={'token': invitation.token})
                )

                # Send invitation email
                try:
                    send_email(
                        subject=f'Invitation to join {org.name} on Blik',
                        message=f'''
Hello,

You've been invited to be the administrator of {org.name} on Blik 360 Feedback Platform.

Click the link below to accept this invitation and create your account:
{invite_url}

This invitation will expire in 7 days.

Best regards,
Blik Team
                        '''.strip(),
                        recipient_list=[admin_email],
                        html_message=f'''
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2>You're Invited!</h2>
        <p>You've been invited to be the administrator of <strong>{org.name}</strong> on Blik 360 Feedback Platform.</p>
        <p style="margin: 30px 0;">
            <a href="{invite_url}" style="display: inline-block; padding: 12px 24px; background-color: #4f46e5; color: white; text-decoration: none; border-radius: 8px;">Accept Invitation</a>
        </p>
        <p style="color: #666; font-size: 14px;">This invitation will expire in 7 days.</p>
        <p>Best regards,<br>Blik Team</p>
    </div>
</body>
</html>
                        ''',
                        from_email=None  # Use default
                    )
                    messages.success(
                        request,
                        f'Organization "{org_name}" created successfully. Invitation sent to {admin_email}.'
                    )
                    return redirect('superuser_create_organization')
                except Exception as e:
                    # Rollback will happen automatically due to transaction.atomic()
                    raise Exception(f'Failed to send invitation email: {e}')

        except Exception as e:
            messages.error(request, f'Failed to create organization: {e}')
            return render(request, 'superuser/create_organization.html')

    # GET request - show form
    # Get recent organizations for reference
    recent_orgs = Organization.objects.order_by('-created_at')[:10]

    return render(request, 'superuser/create_organization.html', {
        'recent_orgs': recent_orgs
    })
