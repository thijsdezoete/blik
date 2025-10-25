"""
Views for organization invitations
"""
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.urls import reverse
from accounts.models import OrganizationInvitation
from core.email import send_email


@login_required
def send_invitation(request):
    """Send invitation to join organization"""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        # Get organization from request or user's profile
        org = request.organization
        if not org and hasattr(request.user, 'profile'):
            org = request.user.profile.organization

        if not org:
            messages.error(request, 'No organization found.')
            return redirect('admin_dashboard')

        if not email:
            messages.error(request, 'Email address is required.')
            return redirect('admin_dashboard')

        # Check if invitation already exists
        existing = OrganizationInvitation.objects.filter(
            organization=org,
            email=email,
            accepted_at__isnull=True
        ).first()

        if existing and existing.is_valid():
            messages.info(request, f'Invitation already sent to {email}')
            return redirect('admin_dashboard')

        # Create new invitation
        invitation = OrganizationInvitation.objects.create(
            organization=org,
            email=email,
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

You've been invited to join {org.name} on Blik 360 Feedback Platform.

Click the link below to accept this invitation and create your account:
{invite_url}

This invitation will expire in 7 days.

Best regards,
{org.name} Team
                '''.strip(),
                recipient_list=[email],
                html_message=f'''
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2>You're Invited!</h2>
        <p>You've been invited to join <strong>{org.name}</strong> on Blik 360 Feedback Platform.</p>
        <p style="margin: 30px 0;">
            <a href="{invite_url}" style="display: inline-block; padding: 12px 24px; background-color: #4f46e5; color: white; text-decoration: none; border-radius: 8px;">Accept Invitation</a>
        </p>
        <p style="color: #666; font-size: 14px;">This invitation will expire in 7 days.</p>
        <p>Best regards,<br>{org.name} Team</p>
    </div>
</body>
</html>
                ''',
                from_email=org.from_email if org.from_email else None
            )
            messages.success(request, f'Invitation sent to {email}')
        except Exception as e:
            messages.error(request, f'Failed to send invitation: {e}')

    return redirect('team_list')


def accept_invitation(request, token):
    """Accept invitation - redirects to login if user exists, or shows signup form"""
    invitation = get_object_or_404(OrganizationInvitation, token=token)

    if not invitation.is_valid():
        messages.error(request, 'This invitation has expired or been used.')
        return redirect('login')

    # Check if user already exists with this email
    from django.contrib.auth.models import User
    existing_user = User.objects.filter(email=invitation.email).first()

    if existing_user:
        # User exists - create profile and mark invitation accepted
        from accounts.models import UserProfile
        profile, created = UserProfile.objects.get_or_create(
            user=existing_user,
            defaults={
                'organization': invitation.organization,
                'can_create_cycles_for_others': invitation.organization.default_users_can_create_cycles
            }
        )

        if not created and profile.organization != invitation.organization:
            messages.error(
                request,
                f'Your account is already linked to {profile.organization.name}. '
                'Please contact support for multi-organization access.'
            )
            return redirect('login')

        # Mark invitation accepted
        invitation.accepted_at = timezone.now()
        invitation.save()

        messages.success(
            request,
            f'Welcome to {invitation.organization.name}! Please log in.'
        )
        return redirect('login')

    # New user - show signup form
    # Store invitation token in session for signup
    request.session['invitation_token'] = token
    request.session['invitation_email'] = invitation.email

    messages.info(
        request,
        f'Welcome! Create your account to join {invitation.organization.name}'
    )
    return redirect('signup_from_invitation')
