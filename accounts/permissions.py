"""
Organization-level permission system using Django's permission framework.

This module provides:
1. Custom permissions for organization admins
2. Decorators for view-level permission checks
3. Utility functions for permission assignment
"""
from functools import wraps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from accounts.models import UserProfile


# Group names
ORG_ADMIN_GROUP = 'Organization Admin'
ORG_MEMBER_GROUP = 'Organization Member'


def ensure_permission_groups():
    """
    Create default permission groups if they don't exist.

    Organization Admin group has permissions to:
    - Invite team members
    - Manage organization settings
    - Delete organization
    - View all reports
    - Create cycles for others

    Organization Member group has permissions to:
    - View own data
    - Submit feedback
    - View own reports
    """
    # Lazy import to avoid DB access during module import
    from django.apps import apps
    if not apps.ready:
        return None, None

    content_type = ContentType.objects.get_for_model(UserProfile)

    # Create or get permissions
    invite_permission, _ = Permission.objects.get_or_create(
        codename='can_invite_members',
        name='Can invite team members',
        content_type=content_type,
    )

    manage_org_permission, _ = Permission.objects.get_or_create(
        codename='can_manage_organization',
        name='Can manage organization settings',
        content_type=content_type,
    )

    delete_org_permission, _ = Permission.objects.get_or_create(
        codename='can_delete_organization',
        name='Can delete organization',
        content_type=content_type,
    )

    view_all_reports_permission, _ = Permission.objects.get_or_create(
        codename='can_view_all_reports',
        name='Can view all organization reports',
        content_type=content_type,
    )

    # Create Organization Admin group
    admin_group, created = Group.objects.get_or_create(name=ORG_ADMIN_GROUP)
    if created or admin_group.permissions.count() == 0:
        admin_group.permissions.set([
            invite_permission,
            manage_org_permission,
            delete_org_permission,
            view_all_reports_permission,
        ])

    # Create Organization Member group
    member_group, _ = Group.objects.get_or_create(name=ORG_MEMBER_GROUP)
    # Members have no special permissions by default

    return admin_group, member_group


def assign_organization_admin(user):
    """
    Assign organization admin permissions to a user.

    This should be called when:
    - A user signs up through Stripe (becomes org owner)
    - An admin promotes another user to admin

    Args:
        user: Django User instance
    """
    ensure_permission_groups()
    admin_group, _ = Group.objects.get_or_create(name=ORG_ADMIN_GROUP)

    # Add to admin group
    user.groups.add(admin_group)

    # Set is_staff flag for backward compatibility
    user.is_staff = True
    user.save()

    # Set can_create_cycles_for_others flag
    if hasattr(user, 'profile'):
        user.profile.can_create_cycles_for_others = True
        user.profile.save()


def assign_organization_member(user, can_create_cycles_for_others=False):
    """
    Assign organization member permissions to a user.

    This should be called when:
    - A user accepts an invitation
    - A new team member is added

    Args:
        user: Django User instance
        can_create_cycles_for_others: Whether member can create cycles for others
    """
    ensure_permission_groups()
    member_group, _ = Group.objects.get_or_create(name=ORG_MEMBER_GROUP)

    # Add to member group
    user.groups.add(member_group)

    # Ensure is_staff is False (not an admin)
    user.is_staff = False
    user.save()

    # Set can_create_cycles_for_others flag
    if hasattr(user, 'profile'):
        user.profile.can_create_cycles_for_others = can_create_cycles_for_others
        user.profile.save()


def remove_from_all_org_groups(user):
    """Remove user from all organization groups."""
    user.groups.filter(name__in=[ORG_ADMIN_GROUP, ORG_MEMBER_GROUP]).delete()


def organization_admin_required(view_func=None, redirect_url='admin_dashboard'):
    """
    Decorator to ensure user is an organization admin.

    Usage:
        @login_required
        @organization_admin_required
        def my_view(request):
            ...

    Or with custom redirect:
        @login_required
        @organization_admin_required(redirect_url='home')
        def my_view(request):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            # Check if user has permission
            if not request.user.has_perm('accounts.can_invite_members'):
                messages.error(
                    request,
                    'You do not have permission to perform this action. '
                    'Only organization administrators can access this feature.'
                )
                return redirect(redirect_url)

            return func(request, *args, **kwargs)
        return wrapper

    # Handle both @organization_admin_required and @organization_admin_required()
    if view_func is None:
        return decorator
    else:
        return decorator(view_func)


def can_manage_organization_required(view_func=None, redirect_url='admin_dashboard'):
    """
    Decorator to ensure user can manage organization settings.

    Usage:
        @login_required
        @can_manage_organization_required
        def settings_view(request):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm('accounts.can_manage_organization'):
                messages.error(
                    request,
                    'You do not have permission to manage organization settings.'
                )
                return redirect(redirect_url)

            return func(request, *args, **kwargs)
        return wrapper

    if view_func is None:
        return decorator
    else:
        return decorator(view_func)


def can_delete_organization_required(view_func=None, redirect_url='admin_dashboard'):
    """
    Decorator to ensure user can delete the organization.

    Usage:
        @login_required
        @can_delete_organization_required
        def delete_org_view(request):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm('accounts.can_delete_organization'):
                messages.error(
                    request,
                    'Only organization administrators can delete the organization.'
                )
                return redirect(redirect_url)

            return func(request, *args, **kwargs)
        return wrapper

    if view_func is None:
        return decorator
    else:
        return decorator(view_func)


def is_organization_admin(user):
    """
    Check if user is an organization admin.

    Args:
        user: Django User instance

    Returns:
        bool: True if user is admin, False otherwise
    """
    return user.has_perm('accounts.can_invite_members')


def can_invite_members(user):
    """Check if user can invite team members."""
    return user.has_perm('accounts.can_invite_members')


def can_manage_organization(user):
    """Check if user can manage organization settings."""
    return user.has_perm('accounts.can_manage_organization')


def can_delete_organization(user):
    """Check if user can delete the organization."""
    return user.has_perm('accounts.can_delete_organization')


def can_view_all_reports(user):
    """Check if user can view all organization reports."""
    return user.has_perm('accounts.can_view_all_reports')
