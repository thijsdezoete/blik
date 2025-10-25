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
    """Attach organization to request based on authenticated user"""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Initialize organization as None
        request.organization = None

        # Skip for anonymous users
        if isinstance(request.user, AnonymousUser) or not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for public endpoints
        exempt_paths = [
            '/feedback/',  # Anonymous feedback submission
            '/reports/view/',  # Public report viewing with token
            '/api/stripe/webhook/',  # Stripe webhooks
            '/static/',
            '/media/',
            '/landing/',
        ]

        if any(request.path.startswith(path) for path in exempt_paths):
            return self.get_response(request)

        # Get user's organization
        # For now, get the first organization (single-tenant or user's org)
        # Future: add User.organization FK for proper multi-tenant support
        if request.user.is_staff or request.user.is_superuser:
            request.organization = Organization.objects.first()

        return self.get_response(request)
