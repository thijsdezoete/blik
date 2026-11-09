"""
Custom permission classes for API endpoints.

These permissions maintain organization isolation and enforce role-based access.
"""
from rest_framework.permissions import BasePermission


class IsOrganizationMember(BasePermission):
    """
    Ensures request has valid organization context.
    Works with both session auth and API tokens.

    Object-level permission checks that the object belongs to the request's organization.
    """

    def has_permission(self, request, view):
        """
        Check if request has organization context.

        Args:
            request: HTTP request object
            view: DRF view

        Returns:
            bool: True if organization is set, False otherwise
        """
        # Check organization is set (by middleware or token auth)
        if not hasattr(request, "organization") or request.organization is None:
            return False
        return True

    def has_object_permission(self, request, view, obj):
        """
        Verify object belongs to request's organization.

        Handles different model relationships:
        - Direct organization FK: obj.organization
        - Via reviewee: obj.reviewee.organization (ReviewCycle)
        - Via cycle: obj.cycle.reviewee.organization (Token, Response)

        Args:
            request: HTTP request object
            view: DRF view
            obj: Model instance being accessed

        Returns:
            bool: True if object belongs to request's organization
        """
        # Direct organization FK
        if hasattr(obj, "organization"):
            return obj.organization == request.organization

        # For ReviewCycle, check via reviewee
        if hasattr(obj, "reviewee"):
            return obj.reviewee.organization == request.organization

        # For ReviewerToken/Response/Report, check via cycle
        if hasattr(obj, "cycle"):
            return obj.cycle.reviewee.organization == request.organization

        # Default deny
        return False


class CanManageOrganization(BasePermission):
    """
    Requires 'can_manage_organization' permission.
    Used for admin-only endpoints (create/update/delete operations).
    """

    def has_permission(self, request, view):
        """
        Check if user has organization management permission.

        Args:
            request: HTTP request object
            view: DRF view

        Returns:
            bool: True if user can manage organization
        """
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.has_perm("accounts.can_manage_organization")


class CanManageQuestionnaires(BasePermission):
    """
    Requires 'can_manage_questionnaires' permission.
    Used for the endpoints that change questionnaires.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.has_perm("accounts.can_manage_questionnaires")


class CanCreateCycles(BasePermission):
    """
    Checks if user can create cycles for others.

    Read operations are allowed for all org members.
    Write operations require can_create_cycles_for_others flag.
    """

    def has_permission(self, request, view):
        """
        Check if user can create/modify cycles.

        Args:
            request: HTTP request object
            view: DRF view

        Returns:
            bool: True if user can create cycles
        """
        # Allow read operations for all authenticated users
        if request.method not in ["POST", "PUT", "PATCH"]:
            return True

        if not request.user or not request.user.is_authenticated:
            return False

        # Check profile flag
        try:
            return request.user.profile.can_create_cycles_for_others
        except:
            return False


class HasAPIPermission(BasePermission):
    """
    Token scopes: a token with permissions may only use what they list, as
    "read:<resource>" for safe methods and "write:<resource>" for the others,
    where the viewset names its resource in `api_resource`.

    A token with empty permissions keeps every right of its creator: that is how
    the settings page creates tokens. Session auth is not affected.
    """

    message = "This API token does not have the scope for this request."

    def has_permission(self, request, view):
        token = getattr(request, "api_token", None)
        if token is None or not token.permissions:
            return True
        resource = getattr(view, "api_resource", None)
        if resource is None:
            return False  # an unnamed resource is never in scope
        access = "read" if request.method in ("GET", "HEAD", "OPTIONS") else "write"
        return token.permissions.get(f"{access}:{resource}") is True


class TokenScopeMixin:
    """Checks the token scope on every request, whatever permissions the action sets."""

    api_resource = None

    def check_permissions(self, request):
        super().check_permissions(request)
        scope = HasAPIPermission()
        if not scope.has_permission(request, self):
            self.permission_denied(request, message=scope.message)


class CanViewAllReports(BasePermission):
    """
    Requires 'can_view_all_reports' permission.
    Used for viewing reports of other users.
    """

    def has_permission(self, request, view):
        """
        Check if user can view all reports.

        Args:
            request: HTTP request object
            view: DRF view

        Returns:
            bool: True if user can view all reports
        """
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.has_perm("accounts.can_view_all_reports")
