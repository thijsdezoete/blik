"""
Superuser-only views for administrative tasks
"""
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.translation import gettext as _

from core.models import Organization
from accounts.models import UserProfile
from core.email import send_welcome_email
from accounts.permissions import assign_organization_admin
from accounts.services import create_user_with_email_as_username
from subscriptions.models import RoundPurchase
from subscriptions.utils import billing_enabled, entitlement, purchased_credits

# ponytail: a sanity cap on a hand-made grant, not a business rule
MAX_GRANTED_CREDITS = 1000


def _billing_label(org):
    """What this organization pays with, for the recent organizations table."""
    mode = entitlement(org)
    if mode in ('subscription', 'lapsed'):
        return org.subscription.get_status_display()
    if mode == 'credits':
        return _('%(count)s credits left') % {'count': purchased_credits(org)}
    return _('Free, no limits')


@login_required
def create_organization(request):
    """
    Superuser-only page to create organizations without a payment.

    Creates the organization and sends an invitation to the specified admin email.
    The invited admin goes through the normal invitation acceptance flow.

    With billing on, review credits can be granted: the organization then works
    like a Single Round customer. Without credits it has no limits.
    """
    if not request.user.is_superuser:
        messages.error(request, _('You do not have permission to create organizations.'))
        return redirect('admin_dashboard')

    billing = billing_enabled()

    def page():
        recent_orgs = Organization.objects.order_by('-created_at')[:10]
        return render(request, 'superuser/create_organization.html', {
            # ponytail: a few queries per row for 10 rows
            'recent_orgs': [(org, _billing_label(org) if billing else None) for org in recent_orgs],
            'billing_enabled': billing,
            'max_credits': MAX_GRANTED_CREDITS,
        })

    if request.method == 'POST':
        org_name = request.POST.get('org_name', '').strip()
        admin_email = request.POST.get('admin_email', '').strip().lower()

        # Validation
        if not org_name:
            messages.error(request, _('Organization name is required.'))
            return page()

        if not admin_email:
            messages.error(request, _('Admin email is required.'))
            return page()

        credits = 0
        if billing:
            try:
                credits = int(request.POST.get('credits') or 0)
            except ValueError:
                credits = -1
            if not 0 <= credits <= MAX_GRANTED_CREDITS:
                messages.error(request, _('Review credits must be a number from 0 to %(max)s.') % {'max': MAX_GRANTED_CREDITS})
                return page()

        # Check if organization with this name already exists
        if Organization.objects.filter(name=org_name).exists():
            messages.error(request, _('Organization "%(name)s" already exists.') % {'name': org_name})
            return page()

        # Check if user with this email already exists
        existing_user = User.objects.filter(email=admin_email).first()
        if existing_user:
            # Check if user already has a profile/organization
            if hasattr(existing_user, 'profile') and existing_user.profile.organization:
                messages.error(
                    request,
                    _('User with email %(email)s already belongs to organization: %(organization)s')
                    % {'email': admin_email, 'organization': existing_user.profile.organization.name}
                )
                return page()

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

                # Create user account with centralized function
                try:
                    user, password = create_user_with_email_as_username(
                        email=admin_email,
                        password=None  # Generate random password
                    )
                except ValueError as e:
                    messages.error(request, _('Failed to create user: %(error)s') % {'error': e})
                    return redirect('superuser_create_organization')

                # Create user profile with admin privileges
                UserProfile.objects.create(
                    user=user,
                    organization=org,
                    can_create_cycles_for_others=True  # Admins can create cycles for others
                )

                # Assign organization admin permissions
                assign_organization_admin(user)

                if credits:
                    RoundPurchase.objects.create(organization=org, cycles_remaining=credits)

                # Send welcome email with credentials
                try:
                    send_welcome_email(user, org, password=password)
                    messages.success(
                        request,
                        _('Organization "%(name)s" created successfully. Login credentials sent to %(email)s.')
                        % {'name': org_name, 'email': admin_email}
                    )
                    return redirect('superuser_create_organization')
                except Exception as e:
                    # Rollback will happen automatically due to transaction.atomic()
                    raise Exception(_('Failed to send welcome email: %(error)s') % {'error': e})

        except Exception as e:
            messages.error(request, _('Failed to create organization: %(error)s') % {'error': e})
            return page()

    return page()
