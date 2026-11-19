"""
Views for organization invitations
"""
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils import translation
from django.utils.crypto import get_random_string
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST
from accounts import sender_identity
from accounts.models import OrganizationInvitation
from accounts.permissions import managers_without_account, organization_admin_required
from core.languages import recipient_language
from core.email import inviter_name, send_email
from core.url import get_absolute_url
from subscriptions.utils import check_user_limit


def invitation_email(org, user, invite_url, message=''):
    """Subject, text and HTML of the invitation email, in the active language."""
    inviter = inviter_name(user)
    context = {
        'organization': org,
        'invite_url': invite_url,
        'inviter_name': inviter,
        'site_name': settings.SITE_NAME,
        'message': message,
    }
    # An email address in the subject looks like spam. The subject names the inviter
    # only by a real name, and an organization named after an email address not at all.
    if sender_identity.named_after_email(org):
        subject = _('Your invitation to %(site_name)s') % {'site_name': settings.SITE_NAME}
    elif user is not None and user.get_full_name():
        subject = _('%(inviter)s invited you to join %(organization)s on %(site_name)s') % {
            'inviter': user.get_full_name(), 'organization': org.name, 'site_name': settings.SITE_NAME}
    else:
        subject = _('Invitation to join %(organization)s on %(site_name)s') % {
            'organization': org.name, 'site_name': settings.SITE_NAME}
    return (subject, render_to_string('emails/team_invitation.txt', context),
            render_to_string('emails/team_invitation.html', context))


def open_invitation(org, email, user, message='', **fields):
    """
    A fresh invitation for this address. An organization has one invitation per
    address, so an expired or used one is made new: new token, seven more days.
    """
    return OrganizationInvitation.objects.update_or_create(
        organization=org, email=email,
        defaults={
            'invited_by': user,
            'message': message,
            'token': get_random_string(64),
            'accepted_at': None,
            'expires_at': timezone.now() + timedelta(days=7),
            'email_queued_at': None, 'email_error': '', 'email_attempts': 0,
            **fields,
        },
    )[0]


def invite(org, email, user, language=None, message=''):
    """
    Create an invitation and send its email. Raises when the email cannot be
    sent, and then leaves no invitation: an open one would stop a second try.
    """
    with transaction.atomic():
        invitation = open_invitation(org, email, user, message)
        # There is no profile yet: the language chosen in the invitation form, else the organization's
        with translation.override(recipient_language(language, organization=org)):
            subject, text, html = invitation_email(
                org, user, get_absolute_url('accept_invitation', token=invitation.token), message)
            send_email(
                subject=subject,
                message=text,
                recipient_list=[email],
                html_message=html,
                from_email=org.from_email if org.from_email else None
            )


@login_required
@organization_admin_required
@require_POST
def invite_managers(request):
    """Invite the selected managers in the org chart who have no account and no open invitation."""
    # The organization middleware does not run for /accounts/ URLs.
    org = request.organization or request.user.profile.organization
    sender_identity.save(request.user, org, request.POST)
    message = request.POST.get('message', '').strip()[:2000]
    selected = {email.lower() for email in request.POST.getlist('emails')}
    # Only queue: the send_queued_invitations cron sends the emails, so a slow
    # mail server does not hold up this request.
    queued = 0
    for manager in managers_without_account(org):
        # The posted addresses only choose from this list; they never add to it.
        if not manager.invited and manager.email.lower() in selected:
            open_invitation(org, manager.email.lower(), request.user, message, email_queued_at=timezone.now())
            queued += 1
    if not queued:
        messages.error(request, _('Select at least one manager.'))
    if queued:
        messages.success(request, ngettext(
            '%(count)s invitation is queued and goes out within about five minutes.',
            '%(count)s invitations are queued and go out within about five minutes.',
            queued) % {'count': queued})
    return redirect('org_chart')


def _open_invitation_or_404(request, pk):
    # The organization middleware does not run for /accounts/ URLs.
    org = request.organization or request.user.profile.organization
    return get_object_or_404(OrganizationInvitation, pk=pk, organization=org, accepted_at__isnull=True)


@login_required
@organization_admin_required
@require_POST
def withdraw_invitation(request, pk):
    """Take back an invitation that is not accepted: its link stops working and a queued email does not go out."""
    invitation = _open_invitation_or_404(request, pk)
    invitation.delete()
    messages.success(request, _('The invitation to %(email)s is withdrawn.') % {'email': invitation.email})
    return redirect('team_list')


@login_required
@organization_admin_required
@require_POST
def resend_invitation(request, pk):
    """Send an open invitation again: a new link, seven more days, the same message. The cron sends it."""
    invitation = _open_invitation_or_404(request, pk)
    open_invitation(invitation.organization, invitation.email, request.user, invitation.message,
                    email_queued_at=timezone.now())
    messages.success(request, _('The invitation to %(email)s is queued and goes out within about five minutes.')
                     % {'email': invitation.email})
    return redirect('team_list')


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

        sender_identity.save(request.user, org, request.POST)
        try:
            invite(org, email, request.user, language=request.POST.get('language'))
            messages.success(request, _('Invitation sent to %(email)s') % {'email': email})
        except Exception as e:
            messages.error(request, _('Failed to send invitation: %(error)s') % {'error': e})

    return redirect('team_list')


@login_required
@require_POST
def save_sender_identity(request):
    """Save the names that the dialog asks for before a form sends email."""
    # The organization middleware does not run for /accounts/ URLs.
    org = request.organization or request.user.profile.organization
    sender_identity.save(request.user, org, request.POST)
    return HttpResponse(status=204)


@login_required
def invitation_preview(request):
    """
    The subject and HTML of an email as it goes out, for the preview next to a form.
    The names typed in the form show in it before they are saved.
    """
    from django.contrib.auth.models import User
    from core.models import Organization
    from reviews.services import reviewer_invitation_example

    org = request.organization or request.user.profile.organization
    # Copies: the preview must not change the user or the organization of this request.
    user = User(first_name=request.user.first_name, last_name=request.user.last_name, email=request.user.email)
    preview_org = Organization(pk=org.pk, name=org.name, default_language=org.default_language)
    sender_identity.apply(user, preview_org, request.GET, sender_identity.missing(request.user, org))

    with translation.override(recipient_language(request.GET.get('language'), organization=org)):
        if request.GET.get('kind') == 'reviewer':
            subject, html = reviewer_invitation_example(preview_org, user)
        else:
            subject, _text, html = invitation_email(
                preview_org, user, '#', message=request.GET.get('message', '')[:2000])
    return JsonResponse({'subject': subject, 'html': html})


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
