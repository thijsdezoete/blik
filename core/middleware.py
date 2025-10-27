from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from .models import Organization

User = get_user_model()


class SetupMiddleware:
    """Middleware to redirect to setup wizard if initial setup is not complete."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if setup is complete
        from accounts.models import UserProfile
        has_user_with_profile = UserProfile.objects.exists()
        has_organization = Organization.objects.exists()
        setup_complete = has_user_with_profile and has_organization

        # Paths that should be accessible even without setup
        allowed_paths = [
            reverse('setup_welcome'),
            reverse('setup_admin'),
            reverse('setup_organization'),
            reverse('setup_email'),
            reverse('setup_complete'),
            '/static/',
            '/health/',
            '/api/',  # Stripe webhooks
            '/landing/',  # Landing pages
        ]

        # Check if current path is allowed
        path_allowed = any(request.path.startswith(path) for path in allowed_paths)

        # Redirect to setup if not complete and path not allowed
        if not setup_complete and not path_allowed:
            return redirect('setup_welcome')

        response = self.get_response(request)
        return response


class OrganizationMiddleware:
    """
    Attach organization to request based on user profile

    For authenticated users:
    - Uses their profile organization
    - Falls back to first organization for staff/superuser without profiles

    For anonymous users:
    - Organization context not available (public endpoints only)
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Initialize organization as None
        request.organization = None

        # Skip for anonymous users on public endpoints
        exempt_paths = [
            '/feedback/',
            '/reports/view/',
            '/api/stripe/webhook/',
            '/static/',
            '/media/',
            '/landing/',
            '/accounts/',
        ]

        if any(request.path.startswith(path) for path in exempt_paths):
            return self.get_response(request)

        # For authenticated users, use their profile organization
        if request.user.is_authenticated:
            try:
                if hasattr(request.user, 'profile'):
                    request.organization = request.user.profile.organization
                elif request.user.is_superuser:
                    # Fallback for superadmin users without profiles
                    request.organization = Organization.objects.first()
            except Exception as e:
                print(f"Error getting organization for user {request.user}: {e}")

        return self.get_response(request)
