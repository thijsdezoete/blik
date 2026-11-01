"""
Organization-level permission system using Django's permission framework.

This module provides:
1. Custom permissions for organization admins
2. Decorators for view-level permission checks
3. Utility functions for permission assignment
"""
from functools import wraps
from django.contrib.auth.decorators import login_required as django_login_required
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _, gettext
from accounts.models import UserProfile


# Group names
ORG_ADMIN_GROUP = 'Organization Admin'
ORG_MEMBER_GROUP = 'Organization Member'

# The grants that make an account an admin. can_view_all_reports and
# can_manage_questionnaires are left out: they may be granted per user.
ADMIN_ROLE_CODENAMES = (
    'can_invite_members',
    'can_manage_organization',
    'can_delete_organization',
)


def ensure_permission_groups():
    """
    Create default permission groups if they don't exist.

    Organization Admin group has permissions to:
    - Invite team members
    - Manage organization settings
    - Delete organization
    - View all reports
    - Create cycles for others
    - Create and edit questionnaires

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
    invite_permission, created = Permission.objects.get_or_create(
        codename='can_invite_members',
        content_type=content_type,
        defaults={'name': 'Can invite team members'},
    )

    manage_org_permission, created = Permission.objects.get_or_create(
        codename='can_manage_organization',
        content_type=content_type,
        defaults={'name': 'Can manage organization settings'},
    )

    delete_org_permission, created = Permission.objects.get_or_create(
        codename='can_delete_organization',
        content_type=content_type,
        defaults={'name': 'Can delete organization'},
    )

    view_all_reports_permission, created = Permission.objects.get_or_create(
        codename='can_view_all_reports',
        content_type=content_type,
        defaults={'name': 'Can view all organization reports'},
    )

    manage_questionnaires_permission, created = Permission.objects.get_or_create(
        codename='can_manage_questionnaires',
        content_type=content_type,
        defaults={'name': 'Can create and edit questionnaires'},
    )

    admin_permissions = [
        invite_permission,
        manage_org_permission,
        delete_org_permission,
        view_all_reports_permission,
        manage_questionnaires_permission,
    ]

    # Create Organization Admin group
    admin_group, created = Group.objects.get_or_create(name=ORG_ADMIN_GROUP)
    if created or admin_group.permissions.count() == 0:
        admin_group.permissions.set(admin_permissions)
    else:
        # Existing installs: add permissions introduced after the group was
        # created. set() would undo manual grants, add() only fills gaps.
        existing = set(admin_group.permissions.values_list('id', flat=True))
        missing = [p for p in admin_permissions if p.id not in existing]
        if missing:
            admin_group.permissions.add(*missing)

    # Create Organization Member group
    member_group, created = Group.objects.get_or_create(name=ORG_MEMBER_GROUP)
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
    admin_group, created = Group.objects.get_or_create(name=ORG_ADMIN_GROUP)

    # Remove from any org group first so role changes are clean
    remove_from_all_org_groups(user)

    # Add to admin group
    user.groups.add(admin_group)

    # The group grants these now; a direct copy would survive a later demotion.
    _drop_direct_grants(
        user, admin_group.permissions.values_list('codename', flat=True))

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
    - An admin is demoted to member

    Args:
        user: Django User instance
        can_create_cycles_for_others: Whether member can create cycles for others
    """
    ensure_permission_groups()
    member_group, created = Group.objects.get_or_create(name=ORG_MEMBER_GROUP)

    # Remove from any org group first — otherwise demoting an admin leaves
    # them in ORG_ADMIN_GROUP and they keep all admin permissions.
    remove_from_all_org_groups(user)

    # Add to member group
    user.groups.add(member_group)

    # Accounts made admin by a direct grant (the old setup page and import)
    # would otherwise stay admin.
    _drop_direct_grants(user, ADMIN_ROLE_CODENAMES)

    # Ensure is_staff is False (not an admin)
    user.is_staff = False
    user.save()

    # Set can_create_cycles_for_others flag
    if hasattr(user, 'profile'):
        user.profile.can_create_cycles_for_others = can_create_cycles_for_others
        user.profile.save()


def _drop_direct_grants(user, codenames):
    """Remove the user's direct grants of these accounts permissions."""
    user.user_permissions.remove(*Permission.objects.filter(
        content_type=ContentType.objects.get_for_model(UserProfile),
        codename__in=list(codenames),
    ))


def set_user_permission(user, codename, granted):
    """Grant or revoke one organization permission on the user itself.

    Groups carry the role. This is the per-user grant that makes a single
    capability assignable without changing the role — an org member who may
    read every report, say, without becoming an admin.
    """
    ensure_permission_groups()
    content_type = ContentType.objects.get_for_model(UserProfile)
    permission = Permission.objects.get(codename=codename, content_type=content_type)

    if granted:
        user.user_permissions.add(permission)
    else:
        user.user_permissions.remove(permission)


def remove_from_all_org_groups(user):
    """Remove user from all organization groups (without deleting the groups)."""
    admin_group = Group.objects.filter(name=ORG_ADMIN_GROUP).first()
    member_group = Group.objects.filter(name=ORG_MEMBER_GROUP).first()
    if admin_group:
        user.groups.remove(admin_group)
    if member_group:
        user.groups.remove(member_group)


def login_required(view_func=None, as_json=False, **kwargs):
    """Drop-in replacement for django.contrib.auth.decorators.login_required.

    Without as_json it delegates to Django's decorator, keeping login_url
    and redirect_field_name — so it can be imported in its place.

    as_json=True answers 401 instead. Django's version redirects to the HTML
    login page; a caller parsing JSON follows that redirect, gets a page of
    markup and fails on the parse.

    Usage:
        @login_required
        def dashboard(request):
            ...

        @login_required(as_json=True)
        def some_api(request):
            ...
    """
    def decorator(func):
        if not as_json:
            return django_login_required(func, **kwargs)

        @wraps(func)
        def wrapper(request, *args, **kw):
            if not request.user.is_authenticated:
                return JsonResponse(
                    {'error': gettext('Authentication required')}, status=401)

            return func(request, *args, **kw)
        return wrapper

    # Handle both @login_required and @login_required(...)
    if view_func is None:
        return decorator

    return decorator(view_func)


def build_permission_decorator(name, permission, default_message,
                               default_redirect='admin_dashboard'):
    """Build a view decorator that gates access on a single permission.

    Users without the permission get an error message and are redirected
    rather than shown a 403.

    Usage:
        @login_required
        @can_manage_organization_required
        def settings_view(request):
            ...

    Or with a redirect and a message specific to the view:
        @can_manage_organization_required(
            redirect_url='reviewee_list',
            message='You do not have permission to edit reviewees.')
        def reviewee_edit(request, reviewee_id):
            ...

    Endpoints whose callers parse JSON pass as_json=True to get a 403 with
    the message in the body; pair it with @login_required(as_json=True).
    They must not queue a message: it would sit in the session and surface
    on whatever page the user opens next, long after the request that
    caused it.
    """

    def decorator_factory(view_func=None, redirect_url=default_redirect,
                          message=default_message, as_json=False):
        def decorator(func):
            @wraps(func)
            def wrapper(request, *args, **kwargs):
                if not request.user.has_perm(permission):
                    if as_json:
                        return JsonResponse({'error': message}, status=403)

                    messages.error(request, message)
                    return redirect(redirect_url)

                return func(request, *args, **kwargs)
            return wrapper

        # Handle both @foo and @foo()
        if view_func is None:
            return decorator

        return decorator(view_func)

    # So tracebacks and repr() name the decorator, not the factory.
    decorator_factory.__name__ = name
    decorator_factory.__qualname__ = name
    decorator_factory.__doc__ = f"Require the '{permission}' permission."

    return decorator_factory


organization_admin_required = build_permission_decorator(
    'organization_admin_required',
    'accounts.can_invite_members',
    _('You do not have permission to perform this action. '
      'Only organization administrators can access this feature.'),
)

can_manage_organization_required = build_permission_decorator(
    'can_manage_organization_required',
    'accounts.can_manage_organization',
    _('You do not have permission to manage organization settings.'),
)

can_delete_organization_required = build_permission_decorator(
    'can_delete_organization_required',
    'accounts.can_delete_organization',
    _('Only organization administrators can delete the organization.'),
)

can_manage_questionnaires_required = build_permission_decorator(
    'can_manage_questionnaires_required',
    'accounts.can_manage_questionnaires',
    _('You do not have permission to create or edit questionnaires.'),
    default_redirect='questionnaire_list',
)


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
    """
    Check if user can view all organization reports.

    can_manage_organization also counts: admin accounts that predate the
    can_view_all_reports permission may only carry the former.
    """
    return (user.has_perm('accounts.can_view_all_reports')
            or user.has_perm('accounts.can_manage_organization'))


def can_manage_questionnaires(user):
    """
    Check if user can create and edit questionnaires.

    Deliberately a permission of its own rather than a synonym for
    can_manage_organization: the two are meant to be grantable separately.
    Existing admins receive it through the Organization Admin group, which
    migration accounts.0009 backfills.
    """
    return user.has_perm('accounts.can_manage_questionnaires')


def visible_cycles(user, queryset, email_field='reviewee__email'):
    """
    Restrict a ReviewCycle (or Report) queryset to what this user may see.

    Org admins see everything in their organization; everyone else only sees
    cycles where they are the reviewee. Reviewees are matched by email because
    there is no FK from Reviewee to User.

    Organization scoping is a separate concern and must already be applied —
    this narrows within an organization, it does not isolate between them.

    Args:
        email_field: path from the queryset's model to the reviewee email
            ('reviewee__email' for ReviewCycle, 'cycle__reviewee__email' for Report)
    """
    if not getattr(user, 'is_authenticated', False):
        return queryset.none()
    if can_view_all_reports(user):
        return queryset
    if not user.email:
        return queryset.none()
    return queryset.filter(**{f'{email_field}__iexact': user.email})


def reviewee_emails_below(user, organization):
    """
    Emails of everyone below this user in the org chart: the members of the
    units they manage, the members of the units those members manage, and so on.

    A manager may read the reports of these people (not run their cycles).
    The user is matched to a Reviewee by email, as everywhere else.
    """
    from accounts.models import OrgUnitMembership

    if not organization or not getattr(user, 'email', ''):
        return set()

    memberships = list(
        OrgUnitMembership.objects
        .filter(unit__organization=organization)
        .values_list('unit_id', 'role', 'reviewee__email')
    )
    managed_units = {}  # email -> unit ids they manage
    members = {}        # unit id -> member emails
    for unit_id, role, email in memberships:
        email = email.lower()
        if role == OrgUnitMembership.MANAGER:
            managed_units.setdefault(email, set()).add(unit_id)
        else:
            members.setdefault(unit_id, set()).add(email)

    me = user.email.lower()
    below, todo = set(), [me]
    while todo:
        for unit_id in managed_units.get(todo.pop(), ()):
            for email in members.get(unit_id, ()):
                if email not in below and email != me:
                    below.add(email)
                    todo.append(email)
    return below
