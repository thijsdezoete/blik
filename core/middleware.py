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
        has_superuser = User.objects.filter(is_superuser=True).exists()
        has_organization = Organization.objects.exists()
        setup_complete = has_superuser and has_organization

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
    Attach organization to request based on subdomain or user profile

    Priority (when ENABLE_MULTITENANCY=True):
    1. Subdomain (e.g., acme.yourdomain.com -> org with slug 'acme')
    2. User profile (for authenticated users)
    3. None (for public pages)

    When ENABLE_MULTITENANCY=False:
    - Subdomain detection is disabled
    - All authenticated users use their profile organization
    - Single-org mode (first organization)
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        # Initialize organization as None
        request.organization = None

        # Only check subdomain if multitenancy is enabled
        if settings.ENABLE_MULTITENANCY:
            # Try to get organization from subdomain first
            host = request.get_host().split(':')[0]  # Remove port
            parts = host.split('.')

            # If subdomain exists (e.g., acme.yourdomain.com)
            if len(parts) > 2:
                subdomain = parts[0]
                try:
                    request.organization = Organization.objects.get(slug=subdomain, is_active=True)
                    # Store in session for signup
                    if hasattr(request, 'session'):
                        request.session['current_organization_id'] = request.organization.id
                except Organization.DoesNotExist:
                    pass

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

        # For authenticated users without subdomain, use their profile
        if not request.organization and request.user.is_authenticated:
            try:
                if hasattr(request.user, 'profile'):
                    request.organization = request.user.profile.organization
                elif request.user.is_staff or request.user.is_superuser:
                    # Fallback for admin users without profiles
                    request.organization = Organization.objects.first()
            except Exception as e:
                print(f"Error getting organization for user {request.user}: {e}")

        return self.get_response(request)
