"""
Views for organization invitations
"""
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils import translation
from django.utils.translation import gettext as _
from accounts.models import OrganizationInvitation
from accounts.permissions import organization_admin_required
from core.languages import recipient_language
from core.email import inviter_name, send_email
from core.url import get_absolute_url
from subscriptions.utils import check_user_limit


@login_required
@organization_admin_required
def send_invitation(request):
    """
    Send invitation to join organization.

    Only organization administrators can invite new team members.
    """
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        # Get organization from request or user's profile
        org = request.organization
        if not org and hasattr(request.user, 'profile'):
            org = request.user.profile.organization

        if not org:
            messages.error(request, _('No organization found.'))
            return redirect('admin_dashboard')

        if not email:
            messages.error(request, _('Email address is required.'))
            return redirect('admin_dashboard')

        # Check user limit
        allowed, error_message = check_user_limit(request)
        if not allowed:
            messages.error(request, error_message)
            return redirect('team_list')

        # Check if invitation already exists
        existing = OrganizationInvitation.objects.filter(
            organization=org,
            email=email,
            accepted_at__isnull=True
        ).first()

        if existing and existing.is_valid():
            messages.info(request, _('Invitation already sent to %(email)s') % {'email': email})
            return redirect('admin_dashboard')

        # Create new invitation
        invitation = OrganizationInvitation.objects.create(
            organization=org,
            email=email,
            invited_by=request.user,
            expires_at=timezone.now() + timedelta(days=7)
        )

        # Build invitation URL
        invite_url = get_absolute_url('accept_invitation', token=invitation.token)

        # Send invitation email
        try:
            # There is no profile yet: the language chosen in the invitation form, else the organization's
            with translation.override(recipient_language(request.POST.get('language'), organization=org)):
                inviter = inviter_name(request.user)
                context = {
                    'organization': org,
                    'invite_url': invite_url,
                    'inviter_name': inviter,
                    'site_name': settings.SITE_NAME,
                }
                if inviter:
                    subject = _('%(inviter)s invited you to join %(organization)s on %(site_name)s') % {
                        'inviter': inviter, 'organization': org.name, 'site_name': settings.SITE_NAME}
                else:
                    subject = _('Invitation to join %(organization)s on %(site_name)s') % {
                        'organization': org.name, 'site_name': settings.SITE_NAME}
                send_email(
                    subject=subject,
                    message=render_to_string('emails/team_invitation.txt', context),
                    recipient_list=[email],
                    html_message=render_to_string('emails/team_invitation.html', context),
                    from_email=org.from_email if org.from_email else None
                )
            messages.success(request, _('Invitation sent to %(email)s') % {'email': email})
        except Exception as e:
            messages.error(request, _('Failed to send invitation: %(error)s') % {'error': e})

    return redirect('team_list')


def accept_invitation(request, token):
    """Accept invitation - redirects to login if user exists, or shows signup form"""
    invitation = get_object_or_404(OrganizationInvitation, token=token)

    if not invitation.is_valid():
        messages.error(request, _('This invitation has expired or been used.'))
        return redirect('login')

    # Check if user already exists with this email
    from django.contrib.auth.models import User
    existing_user = User.objects.filter(email=invitation.email).first()

    if existing_user:
        # User exists - create profile and mark invitation accepted
        from accounts.models import UserProfile
        from accounts.permissions import assign_organization_member

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
                _('Your account is already linked to %(organization)s. '
                  'Please contact support for multi-organization access.')
                % {'organization': profile.organization.name}
            )
            return redirect('login')

        # Assign organization member permissions if profile was just created
        if created:
            assign_organization_member(
                existing_user,
                can_create_cycles_for_others=invitation.organization.default_users_can_create_cycles
            )

        # Mark invitation accepted
        invitation.accepted_at = timezone.now()
        invitation.save()

        messages.success(
            request,
            _('Welcome to %(organization)s! Please log in.') % {'organization': invitation.organization.name}
        )
        return redirect('login')

    # New user - show signup form
    # Store invitation token in session for signup
    request.session['invitation_token'] = token
    request.session['invitation_email'] = invitation.email

    messages.info(
        request,
        _('Welcome! Create your account to join %(organization)s') % {'organization': invitation.organization.name}
    )
    return redirect('signup_from_invitation')
